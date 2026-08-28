"""
Tests for ChromaBackend. Uses a real local chromadb PersistentClient
against a temp directory (Chroma has no meaningful "fake" - it's already
fully local/embedded, so there's no live-credentials gap to skip around,
unlike QdrantBackend/PineconeBackend/WeaviateBackend's tests).
"""
import shutil

import pytest

from ragleap_vectorstores.chroma_backend import ChromaBackend


@pytest.fixture
def backend(tmp_path):
    b = ChromaBackend(persist_directory=str(tmp_path / "chroma_data"))
    b.init_schema(dimensions=3)
    yield b


def _seed(backend):
    backend.insert_document("doc1", "report.pdf", {"source": "upload"})
    backend.insert_chunk("doc1", "report.pdf", 0, "The cat sat on the mat.", 6, [0.1, 0.2, 0.3], {"page": 1})
    backend.insert_chunk("doc1", "report.pdf", 1, "Dogs bark loudly outside.", 5, [0.9, 0.1, 0.1], {"page": 2})
    backend.insert_document("doc2", "notes.txt", {"source": "manual"})
    backend.insert_chunk("doc2", "notes.txt", 0, "Unrelated content here.", 4, [0.5, 0.5, 0.5], {"page": 1})


def test_requires_persist_directory():
    with pytest.raises(ValueError):
        ChromaBackend(persist_directory="")


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
    """Regression guard for the real Chroma constraint (live-verified): a
    plain multi-key `where=` dict raises ValueError - multiple conditions
    must be wrapped in $and. This test would fail loudly if _build_where()
    regressed to a naive dict pass-through."""
    _seed(backend)
    results = backend.search_dense([0.1, 0.2, 0.3], top_k=5, metadata_filter={"document_id": "doc1", "page": 2})
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
