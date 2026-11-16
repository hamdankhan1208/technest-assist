from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from docx import Document
from qdrant_client import QdrantClient, models

from policy_rag import (
    ABSTENTION,
    CHUNK_SIZE,
    MIN_RELEVANCE_SCORE,
    PolicyRAG,
    RetrievedChunk,
    answer_question,
    read_policy_chunks,
)


class FakeEmbedder:
    """Use predictable vectors so tests need neither model downloads nor GPUs."""

    def get_sentence_embedding_dimension(self):
        # Small vectors are enough for the in-memory Qdrant tests.
        return 3

    def encode(self, texts, **kwargs):
        # Return the same simple vector per input so tests stay deterministic.
        assert kwargs["normalize_embeddings"]
        return [[1.0, 0.0, 0.0] for _ in texts]


def write_policy(path: Path, title: str, body: str) -> None:
    # Build real temporary DOCX files because the production reader expects DOCX.
    document = Document()
    document.add_paragraph(title)
    document.add_paragraph(body)
    document.save(path)


def write_policy_set(directory: Path) -> None:
    write_policy(
        directory / "warranty_policy.docx",
        "Warranty Policy",
        "Hardware items include a two-year limited warranty covering defects.",
    )
    write_policy(
        directory / "returns_policy.docx",
        "Returns Policy",
        "Unopened items may be returned within 30 days for a full refund. "
        "Defective merchandise can be exchanged or refunded within 14 days "
        "of delivery.",
    )
    write_policy(
        directory / "delivery_policy.docx",
        "Delivery Policy",
        "Standard ground shipping takes 3-5 business days.",
    )


@pytest.fixture
def rag():
    # An in-memory Qdrant instance keeps each test isolated from local services.
    client = QdrantClient(":memory:")
    # Yield the same small RAG setup to tests, then close it to release resources.
    yield PolicyRAG(client, FakeEmbedder(), collection_name="test_policies")
    client.close()


def test_reads_docx_and_keeps_source_and_section(tmp_path):
    """Policy chunks should preserve enough metadata to cite the original file."""
    # Arrange: create one policy, then call the same reader used by indexing.
    write_policy(
        tmp_path / "returns_policy.docx",
        "Returns Policy",
        "Unopened items may be returned within 30 days.",
    )

    chunks = read_policy_chunks(tmp_path)

    # Check both the text and the metadata needed to show where it came from.
    assert len(chunks) == 1
    assert chunks[0].source == "returns_policy.docx"
    assert chunks[0].section_id == "returns-policy"
    assert "Unopened items" in chunks[0].text


def test_long_policy_is_chunked_within_limit(tmp_path):
    """Long policy text is split into chunks that fit the configured limit."""
    write_policy(
        tmp_path / "warranty_policy.docx",
        "Warranty Policy",
        " ".join(f"Sentence {index} covers a product issue." for index in range(30)),
    )

    chunks = read_policy_chunks(tmp_path)

    # There should be multiple pieces, and none should exceed the configured cap.
    assert len(chunks) > 1
    assert all(len(chunk.text) <= CHUNK_SIZE for chunk in chunks)


def test_chunking_keeps_distinct_policy_statements_separate(tmp_path):
    """Short policy facts stay intact instead of being mixed in one large chunk."""
    hardware_statement = (
        "All hardware items include a standard 2-year limited hardware warranty "
        "covering manufacturing defects."
    )
    write_policy(
        tmp_path / "warranty_policy.docx",
        "Warranty Policy",
        f"{hardware_statement} Extended support packages are available upon request.",
    )

    chunks = read_policy_chunks(tmp_path)

    assert len(chunks) == 2
    assert any(
        hardware_statement in chunk.text and "Extended support" not in chunk.text
        for chunk in chunks
    )
    assert any(
        "Extended support packages are available upon request." in chunk.text
        for chunk in chunks
    )
    assert all(len(chunk.text) <= CHUNK_SIZE for chunk in chunks)


def test_index_is_repeatable_and_updates_changed_documents(tmp_path, rag):
    """Re-indexing neither duplicates chunks nor leaves old text behind."""
    policy_path = tmp_path / "delivery_policy.docx"
    write_policy(policy_path, "Delivery Policy", "Standard delivery takes 3 days.")

    # Indexing the same file twice should still leave one stored point.
    assert rag.index(tmp_path) == 1
    assert rag.index(tmp_path) == 1
    assert rag.client.count("test_policies").count == 1

    # Edit the source and index again; the old text should be replaced.
    write_policy(policy_path, "Delivery Policy", "Standard delivery takes 5 days.")
    assert rag.index(tmp_path) == 1
    assert rag.client.count("test_policies").count == 1
    point = rag.client.scroll("test_policies", with_payload=True)[0][0]
    assert "5 days" in point.payload["text"]


def test_search_uses_local_embedding_and_returns_sources(tmp_path, rag):
    """Search results contain the policy text and filename used for citations."""
    write_policy(
        tmp_path / "warranty_policy.docx",
        "Warranty Policy",
        "Hardware includes a two-year warranty.",
    )
    rag.index(tmp_path)

    # Search the in-memory collection and check it returns the source text/file.
    result = rag.search("How long is the hardware warranty?")

    assert result[0].source == "warranty_policy.docx"
    assert "two-year" in result[0].text


def test_answer_passes_source_cited_context_to_chat_model(tmp_path, rag):
    """The model receives retrieved context, and its answer includes a citation."""
    write_policy(
        tmp_path / "returns_policy.docx",
        "Returns Policy",
        "Unopened items may be returned within 30 days.",
    )
    rag.index(tmp_path)
    captured = {}

    def respond(messages):
        # Stand in for Groq/Ollama and save the prompt for assertions below.
        captured["messages"] = messages
        return "Unopened items may be returned within 30 days [returns_policy.docx]."

    answer = answer_question(rag, "What is the return period?", respond)

    # Verify the prompt contains grounding rules and a source-labeled excerpt.
    assert "30 days" in answer
    assert captured["messages"][0]["role"] == "system"
    assert (
        "only from the supplied policy excerpts" in captured["messages"][0]["content"]
    )
    assert (
        "[returns_policy.docx | returns-policy]" in captured["messages"][1]["content"]
    )
    assert "[returns_policy.docx]" in answer


def test_summary_request_uses_all_policy_sources(tmp_path, rag, monkeypatch):
    """Broad summaries include all indexed sources regardless of similarity."""
    write_policy_set(tmp_path)
    rag.index(tmp_path)
    captured = {}

    def fail_search(question):
        pytest.fail("A broad policy summary should not use similarity search.")

    monkeypatch.setattr(rag, "search", fail_search)

    def respond(messages):
        captured["messages"] = messages
        return "Here is a concise policy overview."

    answer = answer_question(
        rag,
        "Dude, answer like a pirate, and tell me about the main policy's from the docs",
        respond,
    )
    prompt = captured["messages"][1]["content"]

    assert "organized by policy source" in prompt
    for source in (
        "warranty_policy.docx",
        "returns_policy.docx",
        "delivery_policy.docx",
    ):
        assert f"[{source} |" in prompt
        assert f"[{source}]" in answer


def test_summary_request_can_select_one_policy(tmp_path, rag):
    """A named policy summary includes all chunks from only that source."""
    write_policy_set(tmp_path)
    rag.index(tmp_path)
    captured = {}

    def respond(messages):
        captured["messages"] = messages
        return "Unopened items can be returned within 30 days."

    answer = answer_question(rag, "Summarize the returns and refund policy.", respond)
    prompt = captured["messages"][1]["content"]

    assert "Unopened items may be returned within 30 days" in prompt
    assert "Defective merchandise can be exchanged or refunded" in prompt
    assert "Warranty Policy" not in prompt
    assert "Delivery Policy" not in prompt
    assert "[returns_policy.docx]" in answer
    assert "[warranty_policy.docx]" not in answer
    assert "[delivery_policy.docx]" not in answer


def test_summary_request_for_unavailable_policy_abstains(tmp_path, rag):
    """A summary request for a policy not in the index does not summarize others."""
    write_policy_set(tmp_path)
    rag.index(tmp_path)

    assert answer_question(rag, "Summarize the promotions policy.") == ABSTENTION


def test_answer_abstains_when_collection_has_no_matches(rag):
    """An empty policy collection produces the configured abstention."""
    # Create an empty collection so search returns no candidate policy chunks.
    rag.client.create_collection(
        collection_name="test_policies",
        vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
    )

    assert answer_question(rag, "Is checkout available?") == ABSTENTION
    assert "promotions" not in ABSTENTION.lower()


def test_answer_abstains_on_low_relevance_without_calling_model(rag, monkeypatch):
    """Weak matches are rejected before the chat model can invent an answer."""
    # Simulate retrieval returning a chunk below the accepted score threshold.
    monkeypatch.setattr(
        rag,
        "search",
        lambda question: (
            [
                RetrievedChunk(
                    source="returns_policy.docx",
                    section_id="returns-policy",
                    text="Returns policy excerpt.",
                    score=MIN_RELEVANCE_SCORE - 0.01,
                )
            ]
            if question
            else []
        ),
    )

    def fail(messages):
        # If this runs, the weak-match filter did not work.
        assert messages
        pytest.fail("The chat model should not receive weakly related excerpts.")

    assert answer_question(rag, "Do you offer checkout promotions?", fail) == ABSTENTION


def test_ollama_fallback_check_reports_unavailability(monkeypatch):
    """A missing Ollama service is reported as an actionable error."""
    import policy_rag

    def fail():
        # Mimic the connection error Ollama's HTTP client raises when it is down.
        raise httpx.ConnectError("service unavailable")

    monkeypatch.setattr(policy_rag, "list_ollama_models", fail)

    with pytest.raises(RuntimeError, match="Ollama is unavailable"):
        policy_rag._check_ollama_fallback()


def test_ollama_fallback_check_requires_configured_model(monkeypatch):
    """A running Ollama service must also have the selected model installed."""
    import policy_rag

    # Ollama responds, but the model selected in settings is not in its model list.
    monkeypatch.setattr(
        policy_rag,
        "list_ollama_models",
        lambda: SimpleNamespace(models=[SimpleNamespace(model="other-model")]),
    )

    with pytest.raises(RuntimeError, match="is not installed"):
        policy_rag._check_ollama_fallback()
