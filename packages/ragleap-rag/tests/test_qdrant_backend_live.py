"""
Live tests for QdrantBackend against a real running Qdrant instance.
Gated on QDRANT_TEST_URL (e.g. "http://localhost:6333"), same pattern
as the OpenSearch/Upstash live-gated tests in ragleap-vectorstores -
skip cleanly (not fail) when no real instance is configured.

These exist because the fully-mocked suite in test_qdrant_backend.py
already missed a real bug once (the unnormalized cosine similarity
score) - mocks can only be as correct as the assumptions that built
them. This file exercises the real client against a real server.
"""
import os
import shutil
import tempfile
import uuid

import pytest

qdrant_available = True
try:
    import qdrant_client  # noqa: F401
except ImportError:
    qdrant_available = False

QDRANT_TEST_URL = os.environ.get("QDRANT_TEST_URL")

pytestmark = pytest.mark.skipif(
    not qdrant_available or not QDRANT_TEST_URL,
    reason="qdrant-client not installed, or QDRANT_TEST_URL not set - "
           "skipping QdrantBackend tests that require a real running Qdrant instance",
)


@pytest.fixture
def backend():
    from ragleap.vectorstores.qdrant_backend import QdrantBackend

    tmpdir = tempfile.mkdtemp()
    b = QdrantBackend(
        persist_directory=tmpdir,
        url=QDRANT_TEST_URL,
        collection_name=f"ragleap_live_test_{uuid.uuid4().hex[:8]}",
    )
    b.init_schema(4)
    yield b
    try:
        b._client.delete_collection(b.collection_name)
    except Exception:
        pass
    shutil.rmtree(tmpdir, ignore_errors=True)


def _seed(backend):
    backend.insert_document("doc-1", "live.txt", {"tenant": "acme"})
    backend.insert_chunk("doc-1", "live.txt", 0, "identical vector", 2, [1.0, 0.0, 0.0, 0.0], {"tenant": "acme"})
    backend.insert_chunk("doc-1", "live.txt", 1, "orthogonal vector", 2, [0.0, 1.0, 0.0, 0.0], {"tenant": "acme"})
    backend.insert_chunk("doc-1", "live.txt", 2, "opposite vector", 2, [-1.0, 0.0, 0.0, 0.0], {"tenant": "acme"})


def test_init_schema_is_idempotent(backend):
    backend.init_schema(4)  # should not raise on a second call


def test_search_dense_orders_and_normalizes_score(backend):
    _seed(backend)
    results = backend.search_dense([1.0, 0.0, 0.0, 0.0], top_k=5)
    by_text = {r["text"]: r["similarity_score"] for r in results}
    assert by_text["identical vector"] == 1.0
    assert by_text["orthogonal vector"] == 0.5
    assert by_text["opposite vector"] == 0.0


def test_search_dense_metadata_filter(backend):
    _seed(backend)
    matched = backend.search_dense([1.0, 0.0, 0.0, 0.0], top_k=5, metadata_filter={"tenant": "acme"})
    unmatched = backend.search_dense([1.0, 0.0, 0.0, 0.0], top_k=5, metadata_filter={"tenant": "nope"})
    assert len(matched) == 3
    assert len(unmatched) == 0


def test_list_documents_and_get_filename(backend):
    _seed(backend)
    docs = backend.list_documents(10, 0)
    assert docs[0]["chunk_count"] == 3
    assert backend.get_document_filename("doc-1") == "live.txt"


def test_delete_document_removes_vectors(backend):
    _seed(backend)
    assert backend.delete_document("doc-1") is True
    assert backend.search_dense([1.0, 0.0, 0.0, 0.0], top_k=5) == []


def test_supports_sparse_is_false(backend):
    assert backend.supports_sparse() is False
