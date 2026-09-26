"""
Live tests for WeaviateBackend against a real running Weaviate instance.
Gated on WEAVIATE_TEST_URL (e.g. "http://localhost:8081") and
WEAVIATE_TEST_GRPC_PORT (defaults to 50051), same pattern as the
OpenSearch/Upstash/Qdrant live-gated tests - skip cleanly (not fail)
when no real instance is configured.

These exist because the fully-mocked suite in test_weaviate_backend.py
already missed two real bugs once (the hardcoded connect_to_local port,
and the unnormalized/misdirected named-vector search) - mocks can only
be as correct as the assumptions that built them. This file exercises
the real client against a real server.
"""
import os
import shutil
import tempfile
import uuid

import pytest

weaviate_available = True
try:
    import weaviate  # noqa: F401
except ImportError:
    weaviate_available = False

WEAVIATE_TEST_URL = os.environ.get("WEAVIATE_TEST_URL")
WEAVIATE_TEST_GRPC_PORT = int(os.environ.get("WEAVIATE_TEST_GRPC_PORT", "50051"))

pytestmark = pytest.mark.skipif(
    not weaviate_available or not WEAVIATE_TEST_URL,
    reason="weaviate-client not installed, or WEAVIATE_TEST_URL not set - "
           "skipping WeaviateBackend tests that require a real running Weaviate instance",
)


@pytest.fixture
def backend():
    from ragleap.vectorstores.weaviate_backend import WeaviateBackend
    from urllib.parse import urlparse

    parsed = urlparse(WEAVIATE_TEST_URL)
    tmpdir = tempfile.mkdtemp()
    b = WeaviateBackend(
        persist_directory=tmpdir,
        collection_name=f"RagleapLiveTest{uuid.uuid4().hex[:8]}",
        local_host=parsed.hostname or "localhost",
        local_port=parsed.port or 8080,
        local_grpc_port=WEAVIATE_TEST_GRPC_PORT,
    )
    b.init_schema(4)
    yield b
    try:
        b._client.collections.delete(b.collection_name)
    except Exception:
        pass
    try:
        b.close()
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
