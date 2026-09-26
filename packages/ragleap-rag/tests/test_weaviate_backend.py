"""Tests for WeaviateBackend - NOT live-verified against a real
Weaviate instance (same honest caveat as PineconeBackend). Mocks the
actual Weaviate client entirely; every attribute path verified against
the actual installed weaviate-client==4.22.0 package's real source
during development (self.collections/self.data/self.query are real
instance attributes set in __init__, not class-level methods -
confirmed by reading the actual source, not assumed)."""
import pytest
from unittest.mock import MagicMock, patch

weaviate_available = True
try:
    import weaviate  # noqa: F401
except ImportError:
    weaviate_available = False

pytestmark = pytest.mark.skipif(not weaviate_available, reason="weaviate-client not installed")


def _make_backend(tmp_path, **kwargs):
    from ragleap.vectorstores.weaviate_backend import WeaviateBackend
    return WeaviateBackend(persist_directory=str(tmp_path / "wv_data"), cluster_url="https://fake.weaviate.cloud", api_key="fake-key", **kwargs)


def test_requires_persist_directory():
    from ragleap.vectorstores.weaviate_backend import WeaviateBackend
    with pytest.raises(ValueError, match="requires persist_directory"):
        WeaviateBackend(persist_directory="", cluster_url="https://fake.weaviate.cloud")


def test_collection_name_normalized_to_uppercase_first_letter(tmp_path):
    backend = _make_backend(tmp_path, collection_name="myCollection")
    assert backend.collection_name == "MyCollection"


def test_vector_key_construction(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend._vector_key("doc1", 0) == "doc1:0"


def test_deterministic_uuid_is_stable(tmp_path):
    backend = _make_backend(tmp_path)
    uuid1 = backend._deterministic_uuid("doc1:0")
    uuid2 = backend._deterministic_uuid("doc1:0")
    uuid3 = backend._deterministic_uuid("doc1:1")
    assert uuid1 == uuid2  # same input -> same UUID, idempotent
    assert uuid1 != uuid3


def test_insert_document_and_list_documents(tmp_path):
    backend = _make_backend(tmp_path)
    backend.insert_document("doc1", "test.txt", {"tenant": "acme"})
    docs = backend.list_documents(limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0]["document_id"] == "doc1"
    assert docs[0]["metadata"] == {"tenant": "acme"}


def test_insert_chunk_calls_data_insert_with_correct_args(tmp_path):
    backend = _make_backend(tmp_path)
    backend._collection = MagicMock()

    backend.insert_chunk(
        document_id="doc1", document_name="test.txt", chunk_index=0,
        text="chunk text", token_count=5, embedding=[0.1, 0.2], metadata={"tenant": "acme"},
    )

    backend._collection.data.insert.assert_called_once()
    call_kwargs = backend._collection.data.insert.call_args.kwargs
    # live-verified: Configure.Vectors.self_provided() with no name=
    # creates a NAMED vector called "default", not the legacy unnamed
    # vector - insert must use {"default": [...]} or search silently
    # returns zero results (confirmed empirically against real Weaviate).
    assert call_kwargs["vector"] == {"default": [0.1, 0.2]}
    assert call_kwargs["properties"]["document_id"] == "doc1"
    assert call_kwargs["properties"]["tenant"] == "acme"
    assert "uuid" in call_kwargs

    row = backend._conn.execute("SELECT text FROM chunks WHERE vector_key = ?", ("doc1:0",)).fetchone()
    assert row[0] == "chunk text"


def test_search_dense_converts_distance_to_similarity_score(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._collection = MagicMock()

    weaviate_uuid = backend._deterministic_uuid("doc1:0")
    backend._conn.execute(
        "INSERT INTO chunks (vector_key, weaviate_uuid, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', ?, 'doc1', 'test.txt', 0, 'real text', 5, '{}')",
        (weaviate_uuid,),
    )
    backend._conn.commit()

    mock_obj = MagicMock()
    mock_obj.uuid = weaviate_uuid
    mock_obj.metadata.distance = 0.2  # cosine distance 0.2 -> similarity 0.9 (1 - distance/2)
    mock_response = MagicMock()
    mock_response.objects = [mock_obj]
    backend._collection.query.near_vector.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)

    backend._collection.query.near_vector.assert_called_once()
    query_kwargs = backend._collection.query.near_vector.call_args.kwargs
    assert query_kwargs["target_vector"] == "default"

    assert len(results) == 1
    assert results[0]["text"] == "real text"
    # live-verified formula: 1.0 - distance / 2, matching pgvector's own
    # convention - NOT the old 1.0 - distance, which produced raw cosine
    # similarity in [-1, 1] instead of the [0, 1] range every backend uses.
    assert results[0]["similarity_score"] == 0.9


def test_search_dense_skips_orphaned_objects(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._collection = MagicMock()

    mock_obj = MagicMock()
    mock_obj.uuid = "orphaned-uuid-not-in-sqlite"
    mock_response = MagicMock()
    mock_response.objects = [mock_obj]
    backend._collection.query.near_vector.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)
    assert results == []


def test_delete_document_calls_delete_by_id_for_each_chunk(tmp_path):
    backend = _make_backend(tmp_path)
    backend._collection = MagicMock()

    backend.insert_document("doc1", "test.txt", {})
    weaviate_uuid = backend._deterministic_uuid("doc1:0")
    backend._conn.execute(
        "INSERT INTO chunks (vector_key, weaviate_uuid, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', ?, 'doc1', 'test.txt', 0, 'text', 5, '{}')",
        (weaviate_uuid,),
    )
    backend._conn.commit()

    deleted = backend.delete_document("doc1")
    assert deleted is True
    backend._collection.data.delete_by_id.assert_called_once_with(weaviate_uuid)


def test_search_dense_normalizes_cosine_distance_to_unit_range(tmp_path):
    """
    Regression test for the similarity_score normalization fix.
    Weaviate's cosine distance ranges [0, 2] (live-verified against a
    real Weaviate instance: identical/orthogonal/opposite vectors
    returned distance 0.0/1.0/2.0). This confirms the 1.0 - distance/2
    transform at its boundaries, matching pgvector/milvus/qdrant's
    normalized-range convention.
    """
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._collection = MagicMock()

    ids = {}
    for key, text, dist in [("doc1:0", "identical vector", 0.0), ("doc1:1", "orthogonal vector", 1.0), ("doc1:2", "opposite vector", 2.0)]:
        wid = backend._deterministic_uuid(key)
        ids[key] = (wid, dist)
        backend._conn.execute(
            "INSERT INTO chunks (vector_key, weaviate_uuid, document_id, document_name, chunk_index, text, token_count, metadata) "
            "VALUES (?, ?, 'doc1', 'test.txt', ?, ?, 5, '{}')",
            (key, wid, int(key.split(":")[1]), text),
        )
    backend._conn.commit()

    def _mock_obj(key, text):
        wid, dist = ids[key]
        o = MagicMock()
        o.uuid = wid
        o.metadata.distance = dist
        return o

    mock_response = MagicMock()
    mock_response.objects = [
        _mock_obj("doc1:0", "identical vector"),
        _mock_obj("doc1:1", "orthogonal vector"),
        _mock_obj("doc1:2", "opposite vector"),
    ]
    backend._collection.query.near_vector.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)

    assert len(results) == 3
    by_text = {r["text"]: r["similarity_score"] for r in results}
    assert by_text["identical vector"] == 1.0
    assert by_text["orthogonal vector"] == 0.5
    assert by_text["opposite vector"] == 0.0


def test_supports_sparse_is_false(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend.supports_sparse() is False


def test_weaviate_backend_importable_from_vectorstores():
    from ragleap.vectorstores import WeaviateBackend
    assert WeaviateBackend is not None
