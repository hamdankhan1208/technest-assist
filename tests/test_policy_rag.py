from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from docx import Document
from qdrant_client import QdrantClient, models

from policy_rag import (
    ABSTENTION,
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

    # There should be multiple pieces, and none should exceed the 500-char cap.
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 500 for chunk in chunks)


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


def test_answer_abstains_when_collection_has_no_matches(rag):
    """An empty policy collection produces the configured abstention."""
    # Create an empty collection so search returns no candidate policy chunks.
    rag.client.create_collection(
        collection_name="test_policies",
        vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
    )

    assert answer_question(rag, "Is checkout available?") == ABSTENTION


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
