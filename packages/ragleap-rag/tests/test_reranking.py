import pytest
"""Tests for rerank=True on ask() — patches RerankerService.rerank()
directly (not the CrossEncoder internals) so these tests never require
sentence-transformers/torch to be installed."""
from ragleap.reranking import RerankerService


def test_rerank_true_calls_reranker_and_reorders(rag, monkeypatch):
    rag.ingest_text(filename="a.txt", text="Content about apples and fruit.")
    rag.ingest_text(filename="b.txt", text="Content about spaceships and rockets.")

    call_log = []

    def fake_rerank(self, query, chunks, top_k):
        call_log.append({"query": query, "n_chunks_in": len(chunks), "top_k": top_k})
        # Force "spaceships" doc to the top regardless of retrieval order
        chunks = sorted(chunks, key=lambda c: "spaceship" not in c["text"])
        return chunks[:top_k]

    monkeypatch.setattr(RerankerService, "rerank", fake_rerank)

    answer = rag.ask("Tell me something", rerank=True, top_k=1, hybrid=False)

    assert len(call_log) == 1
    assert call_log[0]["top_k"] == 1
    assert answer["sources"] == ["b.txt"]


def test_rerank_false_never_calls_reranker(rag, monkeypatch):
    rag.ingest_text(filename="a.txt", text="Some content.")

    called = {"value": False}

    def fake_rerank(self, query, chunks, top_k):
        called["value"] = True
        return chunks[:top_k]

    monkeypatch.setattr(RerankerService, "rerank", fake_rerank)
    rag.ask("A question", rerank=False)

    assert called["value"] is False


def test_rerank_expands_candidate_pool_before_reranking(rag, monkeypatch):
    """rerank=True should retrieve top_k*4 candidates for the reranker
    to choose from, not just top_k."""
    for i in range(6):
        rag.ingest_text(filename=f"doc{i}.txt", text=f"Content number {i} about various topics.")

    pool_sizes_seen = []

    def fake_rerank(self, query, chunks, top_k):
        pool_sizes_seen.append(len(chunks))
        return chunks[:top_k]

    monkeypatch.setattr(RerankerService, "rerank", fake_rerank)
    rag.ask("various topics", rerank=True, top_k=2, hybrid=False)

    assert pool_sizes_seen[0] <= 8  # top_k(2) * 4, capped by how many chunks actually exist
    assert pool_sizes_seen[0] >= 2


def test_reranking_real_onnx_model_ranks_correctly():
    """
    Real end-to-end test of the actual ONNX reranker (no mocking) -
    downloads the real quantized model on first run (cached after via
    huggingface_hub) and verifies it correctly ranks a genuinely
    relevant passage above an irrelevant one. Skipped automatically if
    the [rerank] extra isn't installed or the model can't be reached,
    so this doesn't block CI runs that don't have network access to
    Hugging Face or the optional dependencies installed.
    """
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    pytest.importorskip("huggingface_hub")

    from ragleap.reranking import RerankerService

    try:
        reranker = RerankerService()
        chunks = [
            {"text": "Bananas are a good source of potassium.", "document_name": "irrelevant.txt"},
            {"text": "Paris is the capital and largest city of France.", "document_name": "relevant.txt"},
        ]
        result = reranker.rerank("What is the capital of France?", chunks, top_k=2)
    except Exception as e:
        pytest.skip(f"Could not reach Hugging Face or load the real model: {e}")

    assert result[0]["document_name"] == "relevant.txt"
    assert result[0]["rerank_score"] > result[1]["rerank_score"]
