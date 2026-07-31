"""Tests for PineconeBackend - NOT live-verified against a real Pinecone
account (same honest caveat as mistral/together/cohere/voyage embedding
providers). These tests mock the actual Pinecone client entirely and
verify: (1) constructor validation, (2) pure helper functions, (3) the
SQLite sidecar's CRUD correctness in isolation, and (4) that the right
Pinecone SDK methods get called with the right arguments and the right
attribute-access pattern (not dict-style) - every attribute path used
here (IndexList.names, IndexStatus.ready, ScoredVector.id/.score) was
verified against the actual installed pinecone==9.1.0 package's real
source code during development, not assumed from documentation alone."""
import pytest
from unittest.mock import MagicMock, patch

pinecone_available = True
try:
    import pinecone  # noqa: F401
except ImportError:
    pinecone_available = False

pytestmark = pytest.mark.skipif(not pinecone_available, reason="pinecone package not installed")


# --- Constructor validation ---

def test_requires_persist_directory(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    with pytest.raises(ValueError, match="requires persist_directory"):
        PineconeBackend(persist_directory="", api_key="fake-key")


def test_requires_api_key(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    with pytest.raises(ValueError, match="No API key"):
        PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key=None)


def test_api_key_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "env-key")
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"))
    assert backend.api_key == "env-key"


def test_default_index_name_and_region():
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        backend = PineconeBackend(persist_directory=d, api_key="fake-key")
        assert backend.index_name == "ragleap"
        assert backend.cloud == "aws"
        assert backend.region == "us-east-1"


def test_creates_sqlite_tables_on_init(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    tables = backend._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {t[0] for t in tables}
    assert "documents" in table_names
    assert "chunks" in table_names


# --- Pure helper functions ---

def test_vector_id_construction(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    assert backend._vector_id("doc1", 0) == "doc1:0"
    assert backend._vector_id("doc1", 5) == "doc1:5"


def test_build_filter_none_when_no_filter(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    assert backend._build_filter(None) is None
    assert backend._build_filter({}) is None


def test_build_filter_translates_to_pinecone_eq_syntax(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    result = backend._build_filter({"tenant": "acme", "region": "us"})
    assert result == {"tenant": {"$eq": "acme"}, "region": {"$eq": "us"}}


# --- SQLite sidecar CRUD (no Pinecone network calls involved) ---

def test_insert_document_and_list_documents(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    backend.insert_document("doc1", "test.txt", {"tenant": "acme"})
    docs = backend.list_documents(limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0]["document_id"] == "doc1"
    assert docs[0]["filename"] == "test.txt"
    assert docs[0]["metadata"] == {"tenant": "acme"}
    assert docs[0]["chunk_count"] == 0


def test_get_document_filename(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key")
    backend.insert_document("doc1", "test.txt", {})
    assert backend.get_document_filename("doc1") == "test.txt"
    assert backend.get_document_filename("nonexistent") is None


# --- Interaction tests: mocked Pinecone client, verifying correct calls ---

def _make_backend_with_mock_pinecone(tmp_path):
    from ragleap.vectorstores.pinecone_backend import PineconeBackend
    backend = PineconeBackend(persist_directory=str(tmp_path / "pc_data"), api_key="fake-key", index_name="test-idx")
    return backend


def test_init_schema_creates_index_when_not_existing(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)

    mock_pc = MagicMock()
    mock_pc.list_indexes.return_value.names = []  # no existing indexes
    mock_status = MagicMock()
    mock_status.ready = True
    mock_pc.describe_index.return_value.status = mock_status
    mock_pc.describe_index.return_value.host = "fake-host.pinecone.io"

    with patch("pinecone.Pinecone", return_value=mock_pc):
        backend.init_schema(dimensions=768)

    mock_pc.create_index.assert_called_once()
    call_kwargs = mock_pc.create_index.call_args.kwargs
    assert call_kwargs["name"] == "test-idx"
    assert call_kwargs["dimension"] == 768
    assert call_kwargs["metric"] == "cosine"
    mock_pc.Index.assert_called_once_with(host="fake-host.pinecone.io")


def test_init_schema_skips_create_when_index_exists(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)

    mock_pc = MagicMock()
    mock_pc.list_indexes.return_value.names = ["test-idx"]  # already exists
    mock_pc.describe_index.return_value.host = "fake-host.pinecone.io"

    with patch("pinecone.Pinecone", return_value=mock_pc):
        backend.init_schema(dimensions=768)

    mock_pc.create_index.assert_not_called()
    mock_pc.Index.assert_called_once_with(host="fake-host.pinecone.io")


def test_insert_chunk_upserts_to_pinecone_with_correct_id_and_metadata(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._index = MagicMock()

    backend.insert_chunk(
        document_id="doc1", document_name="test.txt", chunk_index=2,
        text="some text", token_count=5, embedding=[0.1, 0.2, 0.3],
        metadata={"tenant": "acme"},
    )

    backend._index.upsert.assert_called_once()
    call_kwargs = backend._index.upsert.call_args.kwargs
    vectors = call_kwargs["vectors"]
    assert len(vectors) == 1
    vector_id, embedding, metadata = vectors[0]
    assert vector_id == "doc1:2"
    assert embedding == [0.1, 0.2, 0.3]
    assert metadata["document_id"] == "doc1"
    assert metadata["tenant"] == "acme"

    # Also confirms SQLite got the full text (Pinecone metadata never does)
    row = backend._conn.execute("SELECT text FROM chunks WHERE vector_id = ?", ("doc1:2",)).fetchone()
    assert row[0] == "some text"


def test_search_dense_returns_chunks_with_text_from_sqlite(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._dimensions = 3
    backend._index = MagicMock()

    backend.insert_document("doc1", "test.txt", {})
    backend._conn.execute(
        "INSERT INTO chunks (vector_id, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', 'doc1', 'test.txt', 0, 'real chunk text', 5, '{}')"
    )
    backend._conn.commit()

    mock_match = MagicMock()
    mock_match.id = "doc1:0"
    mock_match.score = 0.95
    mock_response = MagicMock()
    mock_response.matches = [mock_match]
    backend._index.query.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2, 0.3], top_k=5)

    assert len(results) == 1
    assert results[0]["text"] == "real chunk text"
    assert results[0]["chunk_id"] == "doc1:0"
    assert results[0]["similarity_score"] == 0.95
    backend._index.query.assert_called_once()
    assert backend._index.query.call_args.kwargs["vector"] == [0.1, 0.2, 0.3]


def test_search_dense_skips_orphaned_vectors(tmp_path):
    """A vector exists in Pinecone (per the mocked response) but has no
    matching row in the local SQLite sidecar - must skip it gracefully,
    never crash or return a chunk with missing text."""
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._dimensions = 3
    backend._index = MagicMock()

    mock_match = MagicMock()
    mock_match.id = "orphaned-vector-id"
    mock_match.score = 0.9
    mock_response = MagicMock()
    mock_response.matches = [mock_match]
    backend._index.query.return_value = mock_response

    results = backend.search_dense(embedding=[0.1, 0.2, 0.3], top_k=5)
    assert results == []


def test_search_dense_wrong_dimensions_returns_empty(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._dimensions = 768
    backend._index = MagicMock()

    results = backend.search_dense(embedding=[0.1, 0.2, 0.3], top_k=5)  # only 3 dims, not 768
    assert results == []
    backend._index.query.assert_not_called()


def test_delete_document_deletes_from_pinecone_and_sqlite(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._index = MagicMock()

    backend.insert_document("doc1", "test.txt", {})
    backend._conn.execute(
        "INSERT INTO chunks (vector_id, document_id, document_name, chunk_index, text, token_count, metadata) "
        "VALUES ('doc1:0', 'doc1', 'test.txt', 0, 'text', 5, '{}')"
    )
    backend._conn.commit()

    deleted = backend.delete_document("doc1")

    assert deleted is True
    backend._index.delete.assert_called_once_with(ids=["doc1:0"])
    assert backend.get_document_filename("doc1") is None


def test_delete_document_returns_false_when_not_found(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    backend._index = MagicMock()
    assert backend.delete_document("nonexistent") is False


def test_supports_sparse_is_false(tmp_path):
    backend = _make_backend_with_mock_pinecone(tmp_path)
    assert backend.supports_sparse() is False


def test_pinecone_backend_importable_from_vectorstores():
    """Confirms it's actually wired into vectorstores/__init__.py, not
    just existing as an orphaned file."""
    from ragleap.vectorstores import PineconeBackend
    assert PineconeBackend is not None
