"""Tests for QdrantBackend - NOT live-verified against a real Qdrant
instance (same honest caveat as PineconeBackend/WeaviateBackend).
Mocks the actual Qdrant client entirely; every method signature and
pydantic model field used was verified against the actual installed
qdrant-client==1.18.0 package's real source during development."""
import pytest
from unittest.mock import MagicMock

qdrant_available = True
try:
    import qdrant_client  # noqa: F401
except ImportError:
    qdrant_available = False

pytestmark = pytest.mark.skipif(not qdrant_available, reason="qdrant-client not installed")


def _make_backend(tmp_path, **kwargs):
    from ragleap.vectorstores.qdrant_backend import QdrantBackend
    return QdrantBackend(persist_directory=str(tmp_path / "qd_data"), url="https://fake.qdrant.cloud", api_key="fake-key", **kwargs)


def test_requires_persist_directory():
    from ragleap.vectorstores.qdrant_backend import QdrantBackend
    with pytest.raises(ValueError, match="requires persist_directory"):
        QdrantBackend(persist_directory="", url="https://fake.qdrant.cloud")


def test_requires_url(tmp_path):
    from ragleap.vectorstores.qdrant_backend import QdrantBackend
    with pytest.raises(ValueError, match="No url"):
        QdrantBackend(persist_directory=str(tmp_path / "qd_data"), url=None)


def test_url_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://env-configured.qdrant.cloud")
    from ragleap.vectorstores.qdrant_backend import QdrantBackend
    backend = QdrantBackend(persist_directory=str(tmp_path / "qd_data"))
    assert backend.url == "https://env-configured.qdrant.cloud"


def test_vector_key_construction(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend._vector_key("doc1", 0) == "doc1:0"


def test_deterministic_uuid_is_stable(tmp_path):
    backend = _make_backend(tmp_path)
    uuid1 = backend._deterministic_uuid("doc1:0")
    uuid2 = backend._deterministic_uuid("doc1:0")
    assert uuid1 == uuid2


def test_build_filter_translates_correctly(tmp_path):
    backend = _make_backend(tmp_path)
    result = backend._build_filter({"tenant": "acme"})
    assert result is not None
    assert len(result.must) == 1
    assert result.must[0].key == "tenant"
    assert result.must[0].match.value == "acme"


def test_build_filter_none_when_empty(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend._build_filter(None) is None
    assert backend._build_filter({}) is None


def test_insert_document_and_list_documents(tmp_path):
    backend = _make_backend(tmp_path)
    backend.insert_document("doc1", "test.txt", {"tenant": "acme"})
    docs = backend.list_documents(limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0]["metadata"] == {"tenant": "acme"}


def test_insert_chunk_calls_upsert_with_correct_point(tmp_path):
    backend = _make_backend(tmp_path)
    backend._client = MagicMock()

    backend.insert_chunk(
        document_id="doc1", document_name="test.txt", chunk_index=0,
        text="chunk text", token_count=5, embedding=[0.1, 0.2], metadata={"tenant": "acme"},
    )

    backend._client.upsert.assert_called_once()
    call_kwargs = backend._client.upsert.call_args.kwargs
    points = call_kwargs["points"]
    assert len(points) == 1
    assert points[0].vector == [0.1, 0.2]
    assert points[0].payload["document_id"] == "doc1"

    row = backend._conn.execute("SELECT text FROM chunks WHERE vector_key = ?", ("doc1:0",)).fetchone()
    assert row[0] == "chunk text"


def test_search_dense_returns_chunks_with_text_from_sqlite(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._client = MagicMock()

    qdrant_id = backend._deterministic_uuid("doc1:0")
    backend._conn.execute(
        "INSERT INTO chunks (vector_key, qdrant_id, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', ?, 'doc1', 'test.txt', 0, 'real text', 5, '{}')",
        (qdrant_id,),
    )
    backend._conn.commit()

    mock_point = MagicMock()
    mock_point.id = qdrant_id
    mock_point.score = 0.95
    mock_response = MagicMock()
    mock_response.points = [mock_point]
    backend._client.query_points.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)

    assert len(results) == 1
    assert results[0]["text"] == "real text"
    assert results[0]["similarity_score"] == 0.95


def test_search_dense_skips_orphaned_points(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._client = MagicMock()

    mock_point = MagicMock()
    mock_point.id = "orphaned-id-not-in-sqlite"
    mock_response = MagicMock()
    mock_response.points = [mock_point]
    backend._client.query_points.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)
    assert results == []


def test_delete_document_calls_delete_with_point_ids(tmp_path):
    backend = _make_backend(tmp_path)
    backend._client = MagicMock()

    backend.insert_document("doc1", "test.txt", {})
    qdrant_id = backend._deterministic_uuid("doc1:0")
    backend._conn.execute(
        "INSERT INTO chunks (vector_key, qdrant_id, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', ?, 'doc1', 'test.txt', 0, 'text', 5, '{}')",
        (qdrant_id,),
    )
    backend._conn.commit()

    deleted = backend.delete_document("doc1")
    assert deleted is True
    backend._client.delete.assert_called_once_with(collection_name=backend.collection_name, points_selector=[qdrant_id])


def test_supports_sparse_is_false(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend.supports_sparse() is False


def test_qdrant_backend_importable_from_vectorstores():
    from ragleap.vectorstores import QdrantBackend
    assert QdrantBackend is not None
