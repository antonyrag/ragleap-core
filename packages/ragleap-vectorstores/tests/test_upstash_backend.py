"""
Tests for UpstashBackend. Uses a real Upstash Vector index (managed
cloud service - no local/embedded mode exists, so unlike Chroma/LanceDB
this needs real credentials). Reads UPSTASH_VECTOR_REST_URL and
UPSTASH_VECTOR_REST_TOKEN from the environment - tests skip cleanly if
these aren't set, rather than failing confusingly.

The real index must be a pure DENSE index (not hybrid/sparse) with
dimension 1536 - live-verified: a hybrid-configured index rejects
dense-only upserts with "This index requires sparse vectors". Each test
uses a random namespace to avoid colliding with other test runs or with
concurrent CI jobs sharing the same index.
"""
import os
import time
import uuid

import pytest

from ragleap_vectorstores.upstash_backend import UpstashBackend

UPSTASH_URL = os.environ.get("UPSTASH_VECTOR_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN")
DIMENSIONS = 1536

pytestmark = pytest.mark.skipif(
    not (UPSTASH_URL and UPSTASH_TOKEN),
    reason="UPSTASH_VECTOR_REST_URL/TOKEN not set - skipping live Upstash tests",
)


def _vec(seed: int, dim: int = DIMENSIONS) -> list:
    """Random vector seeded per 'topic', NOT a uniform-fill vector.
    Live-verified bug in an earlier version of this fixture: uniform
    vectors like [0.1]*dim and [0.9]*dim are perfectly co-linear (same
    direction, different magnitude only) - cosine similarity between
    them is 1.0 regardless of the fill values, making them
    indistinguishable to a cosine-similarity search. Random vectors with
    different seeds have genuinely different directions in high-dim
    space, giving real separation; the same seed reproduces the same
    vector for exact-match assertions."""
    import random
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(dim)]


@pytest.fixture
def backend(tmp_path):
    ns = "test_" + uuid.uuid4().hex[:10]
    b = UpstashBackend(
        url=UPSTASH_URL,
        token=UPSTASH_TOKEN,
        namespace=ns,
        registry_path=str(tmp_path / "registry.sqlite3"),
    )
    b.init_schema(dimensions=DIMENSIONS)
    yield b
    try:
        b._index.reset(namespace=ns)
    except Exception:
        pass


def _seed(backend):
    backend.insert_document("doc1", "report.pdf", {"source": "upload"})
    backend.insert_chunk("doc1", "report.pdf", 0, "The cat sat on the mat.", 6, _vec(1), {})
    backend.insert_chunk("doc1", "report.pdf", 1, "Dogs bark loudly outside.", 5, _vec(2), {})
    backend.insert_document("doc2", "notes.txt", {"source": "manual"})
    backend.insert_chunk("doc2", "notes.txt", 0, "Unrelated content here.", 4, _vec(3), {})
    time.sleep(1.5)  # Upstash writes are eventually consistent - live-verified need for a short wait


def test_requires_url_and_token():
    with pytest.raises(ValueError):
        UpstashBackend(url="", token="")
    with pytest.raises(ValueError):
        UpstashBackend(url="https://example.upstash.io", token="")


def test_init_schema_rejects_dimension_mismatch(tmp_path):
    b = UpstashBackend(
        url=UPSTASH_URL, token=UPSTASH_TOKEN,
        namespace="test_" + uuid.uuid4().hex[:10],
        registry_path=str(tmp_path / "registry.sqlite3"),
    )
    with pytest.raises(RuntimeError, match="dimension"):
        b.init_schema(dimensions=DIMENSIONS + 1)


def test_insert_and_search_dense_shape(backend):
    _seed(backend)
    results = backend.search_dense(_vec(1), top_k=5)
    assert results, "expected at least one result"
    assert set(results[0].keys()) == {
        "chunk_id", "text", "similarity_score", "document_id", "document_name", "chunk_index",
    }
    assert results[0]["document_id"] == "doc1"
    assert results[0]["chunk_index"] == 0
    assert results[0]["text"] == "The cat sat on the mat."
    assert results[0]["similarity_score"] == 1.0


def test_search_dense_single_key_filter(backend):
    _seed(backend)
    results = backend.search_dense(_vec(1), top_k=5, metadata_filter={"document_id": "doc2"})
    assert results
    assert all(r["document_id"] == "doc2" for r in results)


def test_search_dense_multi_key_filter(backend):
    """Upstash's filter= is a real SQL-like string, so multi-key filters
    combine natively with AND - live-verified, no $and wrapping needed
    unlike Chroma."""
    _seed(backend)
    results = backend.search_dense(_vec(1), top_k=5, metadata_filter={"document_id": "doc1", "chunk_index": 1})
    assert len(results) == 1
    assert results[0]["chunk_id"] == "doc1:1"


def test_search_dense_empty_embedding_returns_empty(backend):
    assert backend.search_dense([], top_k=5) == []


def test_search_sparse_not_supported(backend):
    _seed(backend)
    assert backend.search_sparse("cat", top_k=5) == []


def test_search_hybrid_falls_back_to_dense(backend):
    _seed(backend)
    hybrid = backend.search_hybrid("cat", _vec(1), top_k=5)
    dense = backend.search_dense(_vec(1), top_k=5)
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

    time.sleep(1)
    remaining = backend.search_dense(_vec(1), top_k=5)
    assert all(r["document_id"] != "doc1" for r in remaining)


def test_insert_chunk_upserts_not_duplicates(backend):
    """Regression guard: re-inserting the same document_id/chunk_index
    (same deterministic vector id) overwrites in place via Upstash's
    native upsert semantics - no duplicate, same pattern as Redis's HSET."""
    _seed(backend)
    backend.insert_chunk("doc2", "notes.txt", 0, "UPDATED TEXT", 2, _vec(3), {})
    time.sleep(1)
    results = backend.search_dense(_vec(3), top_k=5)
    assert results[0]["text"] == "UPDATED TEXT"
    docs = backend.list_documents(limit=10, offset=0)
    by_id = {d["document_id"]: d for d in docs}
    assert by_id["doc2"]["chunk_count"] == 1


def test_init_schema_idempotent(backend):
    """Calling init_schema again should reconnect and re-verify
    dimension/type, not error - there's nothing to "reset" since Upstash
    has no create-index call, but it must be safe to call twice."""
    _seed(backend)
    backend.init_schema(dimensions=DIMENSIONS)
    results = backend.search_dense(_vec(1), top_k=5)
    assert len(results) == 3
