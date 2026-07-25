"""Tests for VectorRetrievalService — dense (fake embeddings, plumbing
only), sparse (real Postgres full-text search, genuinely meaningful),
and hybrid RRF fusion. Accesses rag's internal retriever directly for
white-box testing of retrieval behavior that ask() doesn't fully expose."""


def test_sparse_search_finds_real_keyword_matches(rag):
    rag.ingest_text(filename="a.txt", text="This document is about bananas and tropical fruit.")
    rag.ingest_text(filename="b.txt", text="This document is about spaceships and rocket engines.")

    results = rag._retriever.search_sparse_chunks("bananas")
    assert len(results) == 1
    assert results[0]["document_name"] == "a.txt"


def test_sparse_search_no_match_returns_empty(rag):
    rag.ingest_text(filename="a.txt", text="This document is about bananas.")
    results = rag._retriever.search_sparse_chunks("nonexistentxyzword")
    assert results == []


def test_sparse_search_respects_metadata_filter(rag):
    rag.ingest_text(filename="a.txt", text="Content about pricing plans.", metadata={"tenant": "acme"})
    rag.ingest_text(filename="b.txt", text="Content about pricing plans.", metadata={"tenant": "globex"})

    results = rag._retriever.search_sparse_chunks("pricing plans", metadata_filter={"tenant": "acme"})
    assert len(results) == 1
    assert results[0]["document_name"] == "a.txt"


def test_dense_search_respects_embedding_dimension_mismatch(rag):
    """A query embedding of the wrong dimension should be rejected,
    not silently truncated or padded."""
    wrong_dim_embedding = [0.1, 0.2, 0.3]  # rag fixture uses TEST_DIMENSIONS=8
    results = rag._retriever.search_similar_chunks(wrong_dim_embedding)
    assert results == []


def test_dense_search_empty_embedding_returns_empty(rag):
    assert rag._retriever.search_similar_chunks([]) == []


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

    results = rag._retriever.search_hybrid_chunks("zephyrtown", query_embedding=[0.5] * 8, top_k=5)
    assert len(results) >= 1
    assert any(r["document_name"] == "a.txt" for r in results)
    assert all(r["retrieval_method"] == "hybrid_rrf" for r in results)
