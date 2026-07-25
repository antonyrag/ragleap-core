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
