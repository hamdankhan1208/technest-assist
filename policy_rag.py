"""Index policy documents and answer questions using retrieved policy context."""

import argparse
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from docx import Document
import httpx
from ollama import ResponseError, list as list_ollama_models
from pypdf import PdfReader
from qdrant_client import QdrantClient, models

from first_llm_call import OLLAMA_MODEL, generate_response

# Keep settings here so they can be changed without editing the main logic.
POLICY_DIRECTORY = Path(__file__).parent / "data" / "policies"
PDF_DIRECTORY = Path(__file__).parent / "data" / "pdfs"
EMBEDDING_MODEL = os.getenv("POLICY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("POLICY_COLLECTION", "technest_policies")
# Chunks are limited by characters for this small first version of the RAG flow.
CHUNK_SIZE = 145
# This is a similarity score cutoff, not a percent or a confidence probability.
MIN_RELEVANCE_SCORE = 0.70
# BGE recommends this instruction at the start of search queries.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
ABSTENTION = (
    "The available policy documents do not provide an answer to that question. "
    "Please contact customer support for further assistance."
)
POLICY_SUMMARY_INTENT = re.compile(
    r"\b(?:summari[sz](?:e|es|ed|ing|ation)?|summary|overview|"
    r"tell\s+me\s+about|main\s+polic(?:y|ies))\b",
    re.IGNORECASE,
)
POLICY_REFERENCE = re.compile(r"\b(?:polic(?:y|ies)|docs?|documents?)\b", re.I)
POLICY_SUMMARY_ALIASES = {
    "warranty": {"warranty"},
    "returns": {"return", "returns", "refund", "refunds"},
    "delivery": {"delivery", "shipping", "ship"},
}
ALL_POLICY_SUMMARY_TERMS = {
    "all",
    "main",
    "overall",
    "each",
    "every",
    "policies",
    "doc",
    "docs",
    "document",
    "documents",
}
# This instruction is sent to the chat model along with the retrieved policy text.
SYSTEM_PROMPT = (
    "You are TechNest customer support. Answer only from the supplied policy "
    "excerpts. If they do not contain the answer, say that the policy documents "
    "do not provide it. Do not invent or infer policy details. Cite each factual "
    "answer using the exact source filename in square brackets, not the section "
    "identifier."
)


@dataclass(frozen=True)
class PolicyChunk:
    # These are saved together so a retrieved piece can be traced back to its file.
    source: str
    section_id: str
    text: str


@dataclass(frozen=True)
class RetrievedChunk:
    # Search results also include a score, which we use to filter weak matches.
    source: str     #       |
    section_id: str #      |
    text: str    #        |
    score: float # <------


def _section_id(text: str) -> str:
    # Turn a heading into a simple label, e.g. "Returns Policy" -> "returns-policy".
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "policy"


def _split_long_text(text: str, max_chars: int) -> list[str]:
    # Keep even a single oversized token within the storage chunk limit.
    words = text.split()
    chunks = []
    current = ""
    for word in words:
        # A long word with no spaces still needs to be broken up to honor the limit.
        while len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            # Save the current chunk and start a fresh one before it gets too long.
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _chunk_text(text: str, max_chars: int) -> list[str]:
    # Prefer sentence boundaries so retrieved chunks preserve complete facts.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            # If one sentence is too long, split it by words as a fallback.
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_text(sentence, max_chars))
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > max_chars and current:
            # Keep each finished chunk within the character limit.
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _read_docx_chunks(path: Path) -> list[PolicyChunk]:
    """Extract text from a DOCX policy and retain its filename and section."""
    paragraphs = [
        (paragraph.text.strip(), paragraph.style.name if paragraph.style else "")
        for paragraph in Document(path).paragraphs
        if paragraph.text.strip()
    ]
    if not paragraphs:
        return []

    title = paragraphs[0][0]
    section = title
    body: list[str] = []
    chunks: list[PolicyChunk] = []

    def flush_section() -> None:
        if not body:
            return
        prefix = title if section == title else f"{title}\n{section}"
        available_chars = CHUNK_SIZE - len(prefix) - 1
        if available_chars <= 0:
            raise ValueError(
                f"Policy title or section is too long in {path.name}: {section}"
            )
        for text in _chunk_text(" ".join(body), available_chars):
            chunks.append(
                PolicyChunk(
                    source=path.name,
                    section_id=_section_id(section),
                    text=f"{prefix}\n{text}",
                )
            )
        body.clear()

    for text, style_name in paragraphs[1:]:
        if style_name.lower().startswith("heading"):
            flush_section()
            section = text
        else:
            body.append(text)
    flush_section()

    if not any(chunk.source == path.name for chunk in chunks):
        chunks.append(
            PolicyChunk(
                source=path.name,
                section_id=_section_id(title),
                text=title,
            )
        )
    return chunks


def _read_pdf_chunks(path: Path) -> list[PolicyChunk]:
    """Extract text from a PDF datasheet/spec document into policy-like chunks."""
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        return []

    title = path.stem.replace("_", " ").strip() or path.name
    section = title
    chunks: list[PolicyChunk] = []
    lines = [line.strip() for line in re.split(r"\n+", text) if line.strip()]
    body: list[str] = []
    for line in lines:
        if len(line) < 100 and line.lower().endswith((":", "-")):
            if body:
                prefix = title if section == title else f"{title}\n{section}"
                available_chars = CHUNK_SIZE - len(prefix) - 1
                if available_chars <= 0:
                    raise ValueError(
                        f"PDF title or section is too long in {path.name}: {section}"
                    )
                for chunk_text in _chunk_text(" ".join(body), available_chars):
                    chunks.append(
                        PolicyChunk(
                            source=path.name,
                            section_id=_section_id(section),
                            text=f"{prefix}\n{chunk_text}",
                        )
                    )
                body = []
            section = line.rstrip(":-")
        else:
            body.append(line)

    if body:
        prefix = title if section == title else f"{title}\n{section}"
        available_chars = CHUNK_SIZE - len(prefix) - 1
        if available_chars <= 0:
            raise ValueError(
                f"PDF title or section is too long in {path.name}: {section}"
            )
        for chunk_text in _chunk_text(" ".join(body), available_chars):
            chunks.append(
                PolicyChunk(
                    source=path.name,
                    section_id=_section_id(section),
                    text=f"{prefix}\n{chunk_text}",
                )
            )

    if not chunks:
        chunks.append(
            PolicyChunk(
                source=path.name,
                section_id=_section_id(title),
                text=title,
            )
        )
    return chunks


def read_policy_chunks(directory: Path = POLICY_DIRECTORY, include_pdfs: bool = False) -> list[PolicyChunk]:
    """Extract text from each policy and optionally include PDF datasheets/specs."""
    chunks: list[PolicyChunk] = []
    for path in sorted(directory.glob("*.docx")):
        chunks.extend(_read_docx_chunks(path))
    if include_pdfs:
        pdf_dir = directory.parent / "pdfs"
        for path in sorted(pdf_dir.glob("*.pdf")):
            chunks.extend(_read_pdf_chunks(path))
    return chunks


def _point_id(chunk: PolicyChunk) -> str:
    # Stable IDs make repeated indexing an update rather than an append.
    # UUID5 gives identical policy text the same ID each time it is indexed.
    identity = f"{chunk.source}\n{chunk.section_id}\n{chunk.text}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


class PolicyRAG:
    """Connect policy chunking/embeddings to Qdrant search and storage."""

    def __init__(
        self,
        client: QdrantClient,
        embedder,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection or reject an incompatible vector size."""
        # Qdrant needs to know how many numbers are in each embedding vector.
        # Support both method names because sentence-transformers versions differ.
        dimension_method = getattr(self.embedder, "get_embedding_dimension", None)
        if dimension_method is None:
            dimension_method = self.embedder.get_sentence_embedding_dimension
        dimension = dimension_method()
        if not dimension:
            raise ValueError("The embedding model did not report a vector dimension.")

        collections = {
            collection.name for collection in self.client.get_collections().collections
        }
        if self.collection_name not in collections:
            # Cosine distance compares the direction of normalized text vectors.
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            return

        info = self.client.get_collection(self.collection_name)
        configured_vectors = info.config.params.vectors
        if not isinstance(configured_vectors, models.VectorParams):
            raise ValueError(
                f"Collection {self.collection_name!r} must use a single unnamed vector."
            )
        if configured_vectors.size != dimension:
            # Reusing a collection with the wrong vector size makes searches fail;
            # stop now and tell the user how to choose a compatible collection.
            raise ValueError(
                f"Collection {self.collection_name!r} has vector size "
                f"{configured_vectors.size}, but the selected embedding model "
                f"produces {dimension}. Choose a new POLICY_COLLECTION or remove "
                "the old collection before reindexing."
            )

    def _scroll_points(self) -> list:
        # Qdrant returns saved points in pages; collect all pages to find old data.
        points = []
        offset = None
        while True:
            page, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points.extend(page)
            if offset is None:
                return points

    def get_all_chunks(self) -> list[PolicyChunk]:
        """Return every indexed policy chunk in stable source order."""
        collections = {
            collection.name for collection in self.client.get_collections().collections
        }
        if self.collection_name not in collections:
            raise RuntimeError(
                f"Policy collection {self.collection_name!r} is missing; "
                "run the index command first."
            )

        chunks = [
            PolicyChunk(
                source=point.payload["source"],
                section_id=point.payload["section_id"],
                text=point.payload["text"],
            )
            for point in self._scroll_points()
            if point.payload
        ]
        return sorted(
            chunks, key=lambda chunk: (chunk.source, chunk.section_id, chunk.text)
        )

    def index(self, directory: Path = POLICY_DIRECTORY, include_pdfs: bool = False) -> int:
        """Embed policy chunks and remove obsolete points from the collection."""
        # First turn the policy documents into plain text pieces with source labels.
        chunks = read_policy_chunks(directory, include_pdfs=include_pdfs)
        if not chunks:
            if include_pdfs:
                raise ValueError(
                    f"No policy or PDF documents found in {directory} or {directory.parent / 'pdfs'}."
                )
            raise ValueError(f"No Word policy documents found in {directory}.")

        self._ensure_collection()
        # Convert every policy chunk into a numeric vector for similarity search.
        vectors = self.embedder.encode(
            [chunk.text for chunk in chunks],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if len(vectors) != len(chunks):
            # Each text must have exactly one vector or metadata could attach to
            # the wrong policy text when the points are assembled below.
            raise ValueError(
                f"The embedding model returned {len(vectors)} vectors for "
                f"{len(chunks)} policy chunks."
            )
        point_ids = [_point_id(chunk) for chunk in chunks]
        points = [
            models.PointStruct(
                id=point_id,
                vector=[float(value) for value in vector],
                # Payload is regular searchable/displayable metadata, not a vector.
                payload={
                    "source": chunk.source,
                    "section_id": chunk.section_id,
                    "text": chunk.text,
                },
            )
            for point_id, chunk, vector in zip(point_ids, chunks, vectors)
        ]

        existing_points = self._scroll_points()
        # Upsert creates new IDs and replaces points whose stable IDs already exist.
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        wanted_ids = set(point_ids)
        wanted_sources = {chunk.source for chunk in chunks}
        # Upsert first, then remove old versions and documents no longer present.
        stale_ids = [
            point.id
            for point in existing_points
            if point.id not in wanted_ids
            or point.payload.get("source") not in wanted_sources
        ]
        if stale_ids:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=stale_ids),
                wait=True,
            )
        return len(chunks)

    def search(self, question: str, limit: int = 3) -> list[RetrievedChunk]:
        """Return the closest policy chunks, including their source metadata."""
        # Catch mistakes before asking the embedding model or contacting Qdrant.
        if not question.strip():
            raise ValueError("Question must not be empty.")
        if limit < 1:
            raise ValueError("Search limit must be at least one.")

        collections = {
            collection.name for collection in self.client.get_collections().collections
        }
        if self.collection_name not in collections:
            raise RuntimeError(
                f"Policy collection {self.collection_name!r} is missing; "
                "run the index command first."
            )

        vector = self.embedder.encode(
            # BGE's retrieval instruction is intended for search queries.
            [f"{QUERY_PREFIX}{question}"],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=[float(value) for value in vector],
            limit=limit,
            with_payload=True,
        )
        return [
            # Keep the original text and filename so the caller can cite the answer.
            RetrievedChunk(
                source=point.payload["source"],
                section_id=point.payload["section_id"],
                text=point.payload["text"],
                score=float(point.score),
            )
            for point in response.points
            if point.payload
        ]


def _is_policy_summary_request(question: str) -> bool:
    """Identify explicit policy summaries so they do not depend on similarity."""
    terms = set(re.findall(r"[a-z]+", question.lower()))
    mentions_policy = POLICY_REFERENCE.search(question) or any(
        terms.intersection(aliases) for aliases in POLICY_SUMMARY_ALIASES.values()
    )
    return bool(POLICY_SUMMARY_INTENT.search(question) and mentions_policy)


def _select_summary_chunks(
    question: str, chunks: Sequence[PolicyChunk]
) -> list[PolicyChunk]:
    """Select named policy sources, or all sources for an overview request."""
    terms = set(re.findall(r"[a-z]+", question.lower()))
    selected_policies = {
        policy
        for policy, aliases in POLICY_SUMMARY_ALIASES.items()
        if terms.intersection(aliases)
    }
    if not selected_policies:
        if terms.intersection(ALL_POLICY_SUMMARY_TERMS):
            return list(chunks)
        return []

    return [
        chunk
        for chunk in chunks
        if any(
            set(re.findall(r"[a-z]+", chunk.source.lower())).intersection(
                POLICY_SUMMARY_ALIASES[policy]
            )
            for policy in selected_policies
        )
    ]


def answer_question(
    rag: PolicyRAG,
    question: str,
    response_generator: Callable[[Sequence[dict[str, str]]], str] = generate_response,
) -> str:
    summary_request = _is_policy_summary_request(question)
    if summary_request:
        chunks = _select_summary_chunks(question, rag.get_all_chunks())
        context = [(chunk.source, chunk.section_id, chunk.text) for chunk in chunks]
    else:
        # Fact questions retain the existing top-three relevance-filtered search.
        results = rag.search(question)
        context = [
            (result.source, result.section_id, result.text)
            for result in results
            if result.score >= MIN_RELEVANCE_SCORE
        ]

    if not context:
        # Do not let the model guess if retrieval found no relevant policy text.
        return ABSTENTION

    # Include source/section labels beside the text so the model can cite evidence.
    excerpts = "\n\n".join(
        f"[{source} | {section_id}]\n{text}" for source, section_id, text in context
    )
    summary_instruction = (
        "Give a concise overview organized by policy source, and cite the exact "
        "source filename for each policy.\n\n"
        if summary_request
        else ""
    )
    messages = [
        # System instructions set the rules; user content contains the question/data.
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Customer question: {question}\n\n"
                f"{summary_instruction}"
                f"Policy excerpts:\n{excerpts}"
            ),
        },
    ]
    answer = response_generator(messages).strip()
    if not answer:
        raise RuntimeError("The chat provider returned an empty policy answer.")

    # Add citations from retrieved sources if the model omitted exact filenames.
    # This guarantees a filename is shown, but it does not prove each sentence is
    # factually supported; the model still needs to follow the grounding prompt.
    missing_sources = list(
        dict.fromkeys(source for source, _, _ in context if f"[{source}]" not in answer)
    )
    if missing_sources:
        citations = ", ".join(f"[{source}]" for source in missing_sources)
        answer = f"{answer}\n\nSources: {citations}"
    return answer


def _load_embedder():
    # Import lazily so helper code and tests can load without loading the ML stack.
    from sentence_transformers import SentenceTransformer

    # SentenceTransformer downloads the model on the first run if not cached.
    return SentenceTransformer(EMBEDDING_MODEL)


def _check_ollama_fallback() -> None:
    """Fail early if the local fallback service or configured model is missing."""
    try:
        # Listing models checks both that Ollama responds and which models exist.
        response = list_ollama_models()
    except (httpx.HTTPError, ResponseError) as error:
        raise RuntimeError(
            "Ollama is unavailable. Start Ollama and verify the local service "
            "before asking policy questions."
        ) from error

    available = {model.model for model in response.models}
    if OLLAMA_MODEL not in available:
        raise RuntimeError(
            f"Ollama is running, but model {OLLAMA_MODEL!r} is not installed. "
            f"Run `ollama pull {OLLAMA_MODEL}` before asking policy questions."
        )


def _build_rag() -> PolicyRAG:
    # Build the two external pieces used by the RAG flow: Qdrant and embeddings.
    return PolicyRAG(QdrantClient(url=QDRANT_URL), _load_embedder())


def main(argv: Iterable[str] | None = None) -> int:
    """Run indexing or answer one question from the command line."""
    # Subcommands keep indexing separate from asking questions:
    #   python policy_rag.py index
    #   python policy_rag.py ask "What is the warranty?"
    parser = argparse.ArgumentParser(description="Index and query TechNest policies.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser(
        "index", help="Index policy files and optional PDF datasheets in Qdrant."
    )
    index_parser.add_argument(
        "--include-pdfs",
        action="store_true",
        help="Include generated product datasheets and PDF specs in the index.",
    )
    ask_parser = subparsers.add_parser("ask", help="Ask a policy-grounded question.")
    ask_parser.add_argument("question")
    args = parser.parse_args(argv)

    rag = _build_rag()
    try:
        if args.command == "index":
            count = rag.index(include_pdfs=args.include_pdfs)
            print(f"Indexed {count} policy chunks in {COLLECTION_NAME}.")
            return 0

        # Check the local fallback before asking, even if Groq is configured.
        # Groq can fail, and then the shared response helper needs Ollama.
        _check_ollama_fallback()
        provider = (
            "Groq with Ollama fallback" if os.getenv("GROQ_API_KEY") else "Ollama"
        )
        print(f"Chat provider: {provider} (Ollama model: {OLLAMA_MODEL}).")
        print(answer_question(rag, args.question))
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Policy RAG failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
