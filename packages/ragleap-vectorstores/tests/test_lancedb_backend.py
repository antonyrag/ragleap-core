"""
Tests for LanceDBBackend. Uses a real local embedded LanceDB database
against a temp directory (LanceDB, like Chroma, is already fully
local/embedded - no live-credentials gap to skip around).
"""
import pytest

from ragleap_vectorstores.lancedb_backend import LanceDBBackend


@pytest.fixture
def backend(tmp_path):
    b = LanceDBBackend(uri=str(tmp_path / "lancedb_data"))
    b.init_schema(dimensions=3)
    yield b


def _seed(backend):
    backend.insert_document("doc1", "report.pdf", {"source": "upload"})
    backend.insert_chunk("doc1", "report.pdf", 0, "The cat sat on the mat.", 6, [0.1, 0.2, 0.3], {})
    backend.insert_chunk("doc1", "report.pdf", 1, "Dogs bark loudly outside.", 5, [0.9, 0.1, 0.1], {})
    backend.insert_document("doc2", "notes.txt", {"source": "manual"})
    backend.insert_chunk("doc2", "notes.txt", 0, "Unrelated content here.", 4, [0.5, 0.5, 0.5], {})


def test_requires_uri():
    with pytest.raises(ValueError):
        LanceDBBackend(uri="")


def test_insert_and_search_dense_shape(backend):
    _seed(backend)
    results = backend.search_dense([0.1, 0.2, 0.3], top_k=5)
    assert results, "expected at least one result"
    assert set(results[0].keys()) == {
        "chunk_id", "text", "similarity_score", "document_id", "document_name", "chunk_index",
    }
    assert results[0]["chunk_id"] == "doc1:0"
    assert results[0]["text"] == "The cat sat on the mat."


def test_search_dense_single_key_filter(backend):
    _seed(backend)
    results = backend.search_dense([0.1, 0.2, 0.3], top_k=5, metadata_filter={"document_id": "doc2"})
    assert results
    assert all(r["document_id"] == "doc2" for r in results)


def test_search_dense_multi_key_filter(backend):
    """LanceDB's where= accepts a native SQL boolean expression, so
    multi-key filters combine directly with AND - unlike Chroma's $and
    requirement. This test guards that the AND-join actually narrows
    results correctly against real LanceDB."""
    _seed(backend)
    results = backend.search_dense([0.1, 0.2, 0.3], top_k=5, metadata_filter={"document_id": "doc1", "chunk_index": 1})
    assert len(results) == 1
    assert results[0]["chunk_id"] == "doc1:1"


def test_search_dense_empty_embedding_returns_empty(backend):
    assert backend.search_dense([], top_k=5) == []


def test_search_sparse_not_supported(backend):
    _seed(backend)
    assert backend.search_sparse("cat", top_k=5) == []


def test_search_hybrid_falls_back_to_dense(backend):
    _seed(backend)
    hybrid = backend.search_hybrid("cat", [0.1, 0.2, 0.3], top_k=5)
    dense = backend.search_dense([0.1, 0.2, 0.3], top_k=5)
    assert [r["chunk_id"] for r in hybrid] == [r["chunk_id"] for r in dense]


def test_supports_sparse_is_false(backend):
    assert backend.supports_sparse() is False


def test_list_documents(backend):
    _seed(backend)
    docs = backend.list_documents(limit=10, offset=0)
    assert len(docs) == 2
    by_id = {d["document_id"]: d for d in docs}
    assert by_id["doc1"]["chunk_count"] == 2
    assert by_id["doc2"]["chunk_count"] == 1
    assert by_id["doc1"]["filename"] == "report.pdf"
    assert by_id["doc1"]["metadata"] == {"source": "upload"}


def test_get_document_filename(backend):
    _seed(backend)
    assert backend.get_document_filename("doc1") == "report.pdf"
    assert backend.get_document_filename("nonexistent") is None


def test_delete_document_removes_registry_entry_and_vectors(backend):
    _seed(backend)
    assert backend.delete_document("doc1") is True
    assert backend.delete_document("doc1") is False  # already gone

    docs = backend.list_documents(limit=10, offset=0)
    assert [d["document_id"] for d in docs] == ["doc2"]

    remaining = backend.search_dense([0.1, 0.2, 0.3], top_k=5)
    assert all(r["document_id"] != "doc1" for r in remaining)


def test_insert_chunk_upserts_not_duplicates(backend):
    """Regression guard for the real merge_insert-based upsert path
    (live-verified): re-inserting the same document_id/chunk_index
    updates the row in place rather than creating a duplicate."""
    _seed(backend)
    backend.insert_chunk("doc2", "notes.txt", 0, "UPDATED TEXT", 2, [0.5, 0.5, 0.5], {})
    results = backend.search_dense([0.5, 0.5, 0.5], top_k=5)
    assert results[0]["text"] == "UPDATED TEXT"
    docs = backend.list_documents(limit=10, offset=0)
    by_id = {d["document_id"]: d for d in docs}
    assert by_id["doc2"]["chunk_count"] == 1


def test_init_schema_idempotent(backend):
    """Calling init_schema again (e.g. on reconnect) should reopen the
    existing table, not error or reset it."""
    _seed(backend)
    backend.init_schema(dimensions=3)
    results = backend.search_dense([0.1, 0.2, 0.3], top_k=5)
    assert len(results) == 3
