"""Tests for document lifecycle: list_documents, delete_document,
update_document — including the known metadata-loss limitation."""


def test_list_documents_returns_ingested_docs(rag):
    rag.ingest_text(filename="a.txt", text="content about apples")
    rag.ingest_text(filename="b.txt", text="content about bananas")

    docs = rag.list_documents()
    filenames = {d["filename"] for d in docs}
    assert filenames == {"a.txt", "b.txt"}


def test_list_documents_includes_chunk_count(rag):
    rag.ingest_text(filename="a.txt", text="content about apples")
    docs = rag.list_documents()
    assert docs[0]["chunk_count"] >= 1


def test_list_documents_ordered_most_recent_first(rag):
    rag.ingest_text(filename="first.txt", text="first content")
    rag.ingest_text(filename="second.txt", text="second content")
    docs = rag.list_documents()
    assert docs[0]["filename"] == "second.txt"
    assert docs[1]["filename"] == "first.txt"


def test_delete_document_removes_it_and_returns_true(rag):
    result = rag.ingest_text(filename="temp.txt", text="temporary content")
    deleted = rag.delete_document(result.document_id)
    assert deleted is True
    assert result.document_id not in {d["document_id"] for d in rag.list_documents()}


def test_delete_document_unknown_id_returns_false(rag):
    deleted = rag.delete_document("00000000-0000-0000-0000-000000000000")
    assert deleted is False


def test_delete_document_cascades_to_chunks(rag, database_url):
    result = rag.ingest_text(filename="temp.txt", text="temporary content")
    rag.delete_document(result.document_id)

    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chunks WHERE document_id = %s", (result.document_id,))
    remaining = cur.fetchone()[0]
    cur.close()
    conn.close()
    assert remaining == 0


def test_update_document_creates_new_document_id(rag):
    original = rag.ingest_text(filename="v1.txt", text="version one content")
    updated = rag.update_document(original.document_id, text="version two content")
    assert updated.document_id != original.document_id
    assert original.document_id not in {d["document_id"] for d in rag.list_documents()}


def test_update_document_preserves_filename_if_not_given(rag):
    original = rag.ingest_text(filename="stable-name.txt", text="version one")
    updated_id = rag.update_document(original.document_id, text="version two").document_id
    docs = {d["document_id"]: d["filename"] for d in rag.list_documents()}
    assert docs[updated_id] == "stable-name.txt"


def test_update_document_renames_when_filename_given(rag):
    original = rag.ingest_text(filename="old-name.txt", text="content")
    updated = rag.update_document(original.document_id, text="content v2", filename="new-name.txt")
    docs = {d["document_id"]: d["filename"] for d in rag.list_documents()}
    assert docs[updated.document_id] == "new-name.txt"


def test_update_document_known_limitation_metadata_is_lost(rag, database_url):
    """
    Documents a REAL, currently-open limitation (see README/Part 5
    pending list): update_document() is delete + re-ingest, and does
    not forward the original document's metadata to the new one. This
    test locks in current (unfixed) behavior so a future fix is a
    deliberate, visible change to this test — not a silent behavior
    change nobody notices.
    """
    original = rag.ingest_text(filename="tagged.txt", text="content", metadata={"tenant": "acme"})
    updated = rag.update_document(original.document_id, text="content v2")

    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("SELECT metadata FROM documents WHERE id = %s", (updated.document_id,))
    stored_metadata = cur.fetchone()[0]
    cur.close()
    conn.close()

    assert stored_metadata == {}, (
        "If this fails, update_document() now preserves metadata — "
        "great! Update this test to assert the new (better) behavior "
        "and remove the known-limitation note in the README."
    )
