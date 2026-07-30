"""Real tests for FAISSBackend - genuine FAISS index + SQLite sidecar,
no mocking of the backend itself. Skipped automatically if the
[faiss] extra isn't installed, so it never blocks CI runs without it."""
import pytest

faiss_available = True
try:
    import faiss  # noqa: F401
except ImportError:
    faiss_available = False

pytestmark = pytest.mark.skipif(not faiss_available, reason="faiss-cpu not installed")


@pytest.fixture
def faiss_rag(database_url, tmp_path):
    """A RagLeap instance using FAISSBackend instead of the default
    PgVectorBackend - conversation memory still uses database_url
    (Postgres), since memory is always backend-independent."""
    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
    from ragleap.vectorstores import FAISSBackend
    from conftest import TEST_DIMENSIONS

    backend = FAISSBackend(persist_directory=str(tmp_path / "faiss_data"))
    rag = RagLeap(
        database_url=database_url,
        vector_backend=backend,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
    )
    rag.init_schema()
    return rag


def test_faiss_ingest_and_ask_roundtrip(faiss_rag):
    result = faiss_rag.ingest_text("apples.txt", "This document is about apples and orchards.")
    assert result.chunks_stored == 1

    answer = faiss_rag.ask("Tell me about apples", top_k=1)
    assert answer["sources"] == ["apples.txt"]


def test_faiss_dense_search_finds_correct_document(faiss_rag):
    """Dense-only search with a non-semantic fake embedder can only
    reliably prove exact-vector nearest-neighbor lookup works, not
    that paraphrased text is semantically closest - the fake embedder
    has no real semantic meaning, unlike the pgvector hybrid tests
    which get genuine ranking signal from real Postgres full-text
    search underneath. Querying with the exact ingested text guarantees
    an identical vector and a correct, non-coincidental match."""
    faiss_rag.ingest_text("a.txt", "Content about apples and fruit.")
    faiss_rag.ingest_text("b.txt", "Content about spaceships and rockets.")

    answer = faiss_rag.ask("Content about apples and fruit.", top_k=1)
    assert answer["sources"] == ["a.txt"]


def test_faiss_backend_does_not_support_sparse(faiss_rag):
    assert faiss_rag._vector_backend.supports_sparse() is False


def test_faiss_hybrid_mode_gracefully_degrades_to_dense(faiss_rag):
    """hybrid=True should not crash against a backend with no sparse
    support - it should just behave like dense-only search."""
    faiss_rag.ingest_text("a.txt", "Unique content about zebras.")
    answer = faiss_rag.ask("zebras", hybrid=True, top_k=1)
    assert answer["sources"] == ["a.txt"]


def test_faiss_list_documents(faiss_rag):
    faiss_rag.ingest_text("a.txt", "First document content.")
    faiss_rag.ingest_text("b.txt", "Second document content.")

    docs = faiss_rag.list_documents()
    filenames = {d["filename"] for d in docs}
    assert filenames == {"a.txt", "b.txt"}


def test_faiss_delete_document_removes_it(faiss_rag):
    result = faiss_rag.ingest_text("temp.txt", "Temporary content.")
    deleted = faiss_rag.delete_document(result.document_id)
    assert deleted is True
    assert faiss_rag.list_documents() == []


def test_faiss_delete_unknown_document_returns_false(faiss_rag):
    assert faiss_rag.delete_document("nonexistent-id") is False


def test_faiss_metadata_filter_post_filters_correctly(faiss_rag):
    faiss_rag.ingest_text("a.txt", "Pricing content here.", metadata={"tenant": "acme"})
    faiss_rag.ingest_text("b.txt", "Pricing content here too.", metadata={"tenant": "globex"})

    answer = faiss_rag.ask("pricing content", metadata_filter={"tenant": "acme"}, top_k=5)
    assert answer["sources"] == ["a.txt"]


def test_faiss_update_document_preserves_filename(faiss_rag):
    original = faiss_rag.ingest_text("stable.txt", "Version one content.")
    updated = faiss_rag.update_document(original.document_id, text="Version two content.")

    docs = {d["document_id"]: d["filename"] for d in faiss_rag.list_documents()}
    assert docs[updated.document_id] == "stable.txt"


def test_faiss_persistence_across_backend_instances(tmp_path, database_url):
    """The real point of persist_directory= - data survives a fresh
    FAISSBackend instance pointed at the same directory, proving this
    isn't just in-process caching."""
    from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
    from ragleap.vectorstores import FAISSBackend
    from conftest import TEST_DIMENSIONS

    persist_dir = str(tmp_path / "faiss_persist_test")

    backend1 = FAISSBackend(persist_directory=persist_dir)
    rag1 = RagLeap(
        database_url=database_url, vector_backend=backend1,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
    )
    rag1.init_schema()
    rag1.ingest_text("persisted.txt", "This content should survive a restart.")

    # Fresh backend instance, same directory - simulates a process restart
    backend2 = FAISSBackend(persist_directory=persist_dir)
    rag2 = RagLeap(
        database_url=database_url, vector_backend=backend2,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
    )
    rag2.init_schema()

    docs = rag2.list_documents()
    assert len(docs) == 1
    assert docs[0]["filename"] == "persisted.txt"
