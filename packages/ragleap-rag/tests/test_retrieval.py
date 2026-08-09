import pytest

"""Tests for the active VectorBackend's retrieval methods - dense (fake
embeddings, plumbing only), sparse (real Postgres full-text search,
genuinely meaningful), and hybrid RRF fusion. Accesses rag's internal
_vector_backend directly for white-box testing of retrieval behavior
that ask() doesn't fully expose."""


def test_sparse_search_finds_real_keyword_matches(rag):
    rag.ingest_text(filename="a.txt", text="This document is about bananas and tropical fruit.")
    rag.ingest_text(filename="b.txt", text="This document is about spaceships and rocket engines.")

    results = rag._vector_backend.search_sparse("bananas", top_k=5)
    assert len(results) == 1
    assert results[0]["document_name"] == "a.txt"


def test_sparse_search_no_match_returns_empty(rag):
    rag.ingest_text(filename="a.txt", text="This document is about bananas.")
    results = rag._vector_backend.search_sparse("nonexistentxyzword", top_k=5)
    assert results == []


def test_sparse_search_respects_metadata_filter(rag):
    rag.ingest_text(filename="a.txt", text="Content about pricing plans.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Content about pricing plans.", metadata={"tenant": "globex"})

    results = rag._vector_backend.search_sparse("pricing plans", top_k=5, metadata_filter={"tenant": "acme"})
    assert len(results) == 1
    assert results[0]["document_name"] == "a.txt"


def test_dense_search_respects_embedding_dimension_mismatch(rag):
    """A query embedding of the wrong dimension should be rejected or
    return no results, not crash."""
    wrong_dim_embedding = [0.1, 0.2, 0.3]  # rag fixture uses TEST_DIMENSIONS=8
    results = rag._vector_backend.search_dense(wrong_dim_embedding, top_k=5)
    assert results == []


def test_dense_search_empty_embedding_returns_empty(rag):
    assert rag._vector_backend.search_dense([], top_k=5) == []


def test_hybrid_search_prefers_keyword_match_via_sparse_signal(rag):
    """Dense (fake) embeddings carry no real semantic signal, so a
    query that keyword-matches one document should still surface it
    near the top via the sparse half of RRF fusion."""
    rag.ingest_text(filename="a.txt", text="This document specifically discusses giraffes.")
    rag.ingest_text(filename="b.txt", text="This document discusses something else entirely.")

    answer = rag.ask("giraffes", hybrid=True, top_k=1)
    assert answer["sources"] == ["a.txt"]


def test_hybrid_search_combines_dense_and_sparse_result_sets(rag):
    rag.ingest_text(filename="a.txt", text="Unique keyword zephyrtown appears here.")
    rag.ingest_text(filename="b.txt", text="Completely different unrelated content.")

    results = rag._vector_backend.search_hybrid("zephyrtown", embedding=[0.5] * 8, top_k=5)
    assert len(results) >= 1
    assert any(r["document_name"] == "a.txt" for r in results)
    assert all(r["retrieval_method"] == "hybrid_rrf" for r in results)


def test_backend_reports_sparse_support(rag):
    """PgVectorBackend (the default) genuinely supports sparse search -
    this isn't a formality, ask()/ask_stream() could check it before
    assuming hybrid mode does anything beyond dense search."""
    assert rag._vector_backend.supports_sparse() is True


def test_retrieve_returns_chunks_without_generating_answer(rag, monkeypatch):
    """retrieve() must never call generation - verify by making the
    generator explode if invoked, so a silent regression back to
    calling generate_answer() fails loudly instead of just costing
    extra tokens unnoticed."""
    from ragleap.generation import GenerationService

    def _explode(self, *args, **kwargs):
        raise AssertionError("retrieve() must not call generate_answer()")

    monkeypatch.setattr(GenerationService, "generate_answer", _explode)

    rag.ingest_text(filename="a.txt", text="This document specifically discusses giraffes.")
    chunks = rag.retrieve("giraffes", top_k=1)

    assert len(chunks) == 1
    assert chunks[0]["document_name"] == "a.txt"
    assert "text" in chunks[0]
    assert "answer" not in chunks[0]


def test_retrieve_respects_top_k(rag):
    rag.ingest_text(filename="a.txt", text="Alpha content one.")
    rag.ingest_text(filename="b.txt", text="Alpha content two.")
    rag.ingest_text(filename="c.txt", text="Alpha content three.")

    chunks = rag.retrieve("Alpha content", top_k=2)
    assert len(chunks) <= 2


def test_retrieve_respects_metadata_filter(rag):
    rag.ingest_text(filename="a.txt", text="Content about pricing plans.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Content about pricing plans.", metadata={"tenant": "globex"})

    chunks = rag.retrieve("pricing plans", top_k=5, metadata_filter={"tenant": "acme"})
    assert len(chunks) == 1
    assert chunks[0]["document_name"] == "a.txt"


def test_retrieve_dense_only_when_hybrid_false(rag):
    rag.ingest_text(filename="a.txt", text="Some content about widgets.")
    chunks = rag.retrieve("widgets", top_k=5, hybrid=False)
    # Dense-only path shouldn't tag results as hybrid_rrf.
    assert all(c.get("retrieval_method") != "hybrid_rrf" for c in chunks)


def test_retrieve_no_documents_returns_empty(rag):
    """Note: NOT testing "no semantic match" with an ingested document -
    the rag fixture uses fake deterministic pseudo-embeddings with no
    real semantic signal (see conftest.py), so with only one document
    in the corpus, dense search always returns it as nearest-neighbor
    regardless of query content. That is expected fake-embedder
    behavior, not a retrieve() bug - caught by an earlier, wrongly-
    written version of this test. Testing the unambiguous case instead:
    zero ingested documents must return zero chunks."""
    chunks = rag.retrieve("anything", top_k=5)
    assert chunks == []


def test_retrieve_with_rerank_does_not_crash(rag):
    """rerank=True lazily constructs a RerankerService - just verify
    the plumbing doesn't break, not reranking quality (out of scope
    here, already covered in test_reranking.py). Skips cleanly if the
    optional 'rerank' extra isn't installed, matching the pattern
    already established in test_reranking.py - CI doesn't install this
    extra by default, and that is correct: it is optional, not required."""
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    pytest.importorskip("huggingface_hub")

    rag.ingest_text(filename="a.txt", text="Some content for reranking test.")
    chunks = rag.retrieve("content", top_k=3, rerank=True)
    assert isinstance(chunks, list)
