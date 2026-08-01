"""Tests for MilvusBackend - NOT live-verified against a real Milvus/
Zilliz Cloud instance (same honest caveat as the other new vector
backends this session). Mocks the actual pymilvus MilvusClient
entirely; every method signature used was verified against the actual
installed pymilvus==3.0.1 package's real source during development
(including that id_type="string" is a genuinely supported primary key
type, not assumed from documentation alone)."""
import pytest
from unittest.mock import MagicMock

pymilvus_available = True
try:
    import pymilvus  # noqa: F401
except ImportError:
    pymilvus_available = False

pytestmark = pytest.mark.skipif(not pymilvus_available, reason="pymilvus not installed")


def _make_backend(tmp_path, **kwargs):
    from ragleap.vectorstores.milvus_backend import MilvusBackend
    return MilvusBackend(persist_directory=str(tmp_path / "mv_data"), uri="https://fake.zillizcloud.com", token="fake-token", **kwargs)


def test_requires_persist_directory():
    from ragleap.vectorstores.milvus_backend import MilvusBackend
    with pytest.raises(ValueError, match="requires persist_directory"):
        MilvusBackend(persist_directory="", uri="https://fake.zillizcloud.com")


def test_requires_uri(tmp_path):
    from ragleap.vectorstores.milvus_backend import MilvusBackend
    with pytest.raises(ValueError, match="No uri"):
        MilvusBackend(persist_directory=str(tmp_path / "mv_data"), uri=None)


def test_uri_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("MILVUS_URI", "https://env-configured.zillizcloud.com")
    from ragleap.vectorstores.milvus_backend import MilvusBackend
    backend = MilvusBackend(persist_directory=str(tmp_path / "mv_data"))
    assert backend.uri == "https://env-configured.zillizcloud.com"


def test_vector_key_construction(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend._vector_key("doc1", 0) == "doc1:0"
    # Unlike Pinecone/Qdrant/Weaviate, Milvus uses the raw vector_key
    # directly as its string primary key - no UUID indirection needed.


def test_build_filter_expr_single_condition(tmp_path):
    backend = _make_backend(tmp_path)
    expr = backend._build_filter_expr({"tenant": "acme"})
    assert expr == 'tenant == "acme"'


def test_build_filter_expr_multiple_conditions_anded(tmp_path):
    backend = _make_backend(tmp_path)
    expr = backend._build_filter_expr({"tenant": "acme", "region": "us"})
    assert " and " in expr
    assert 'tenant == "acme"' in expr
    assert 'region == "us"' in expr


def test_build_filter_expr_numeric_value_not_quoted(tmp_path):
    backend = _make_backend(tmp_path)
    expr = backend._build_filter_expr({"chunk_index": 5})
    assert expr == "chunk_index == 5"


def test_build_filter_expr_empty_when_no_filter(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend._build_filter_expr(None) == ""
    assert backend._build_filter_expr({}) == ""


def test_insert_document_and_list_documents(tmp_path):
    backend = _make_backend(tmp_path)
    backend.insert_document("doc1", "test.txt", {"tenant": "acme"})
    docs = backend.list_documents(limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0]["metadata"] == {"tenant": "acme"}


def test_insert_chunk_calls_insert_with_correct_row(tmp_path):
    backend = _make_backend(tmp_path)
    backend._client = MagicMock()

    backend.insert_chunk(
        document_id="doc1", document_name="test.txt", chunk_index=0,
        text="chunk text", token_count=5, embedding=[0.1, 0.2], metadata={"tenant": "acme"},
    )

    backend._client.insert.assert_called_once()
    call_kwargs = backend._client.insert.call_args.kwargs
    data = call_kwargs["data"]
    assert len(data) == 1
    assert data[0]["id"] == "doc1:0"
    assert data[0]["vector"] == [0.1, 0.2]
    assert data[0]["tenant"] == "acme"

    row = backend._conn.execute("SELECT text FROM chunks WHERE vector_key = ?", ("doc1:0",)).fetchone()
    assert row[0] == "chunk text"


def test_search_dense_returns_chunks_with_text_from_sqlite(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._client = MagicMock()

    backend._conn.execute(
        "INSERT INTO chunks (vector_key, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', 'doc1', 'test.txt', 0, 'real text', 5, '{}')"
    )
    backend._conn.commit()

    # search() returns List[List[dict]] - list per query vector
    backend._client.search.return_value = [[{"id": "doc1:0", "distance": 0.87}]]

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)

    assert len(results) == 1
    assert results[0]["text"] == "real text"
    assert results[0]["similarity_score"] == 0.87


def test_search_dense_skips_orphaned_hits(tmp_path):
    backend = _make_backend(tmp_path)
    backend._dimensions = 2
    backend._client = MagicMock()

    backend._client.search.return_value = [[{"id": "orphaned-not-in-sqlite", "distance": 0.5}]]

    results = backend.search_dense(embedding=[0.1, 0.2], top_k=5)
    assert results == []


def test_delete_document_calls_delete_with_vector_keys(tmp_path):
    backend = _make_backend(tmp_path)
    backend._client = MagicMock()

    backend.insert_document("doc1", "test.txt", {})
    backend._conn.execute(
        "INSERT INTO chunks (vector_key, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', 'doc1', 'test.txt', 0, 'text', 5, '{}')"
    )
    backend._conn.commit()

    deleted = backend.delete_document("doc1")
    assert deleted is True
    backend._client.delete.assert_called_once_with(collection_name=backend.collection_name, ids=["doc1:0"])


def test_supports_sparse_is_false(tmp_path):
    backend = _make_backend(tmp_path)
    assert backend.supports_sparse() is False


def test_milvus_backend_importable_from_vectorstores():
    from ragleap.vectorstores import MilvusBackend
    assert MilvusBackend is not None
