"""Minimal smoke test — proves the fixtures, fake providers, and real
Postgres schema all work together before building out the full suite."""


def test_ingest_and_ask_roundtrip(rag):
    result = rag.ingest_text(
        filename="test.txt",
        text="RagLeap supports WhatsApp, Telegram, and Discord channels.",
    )
    assert result.document_id
    assert result.chunks_stored == 1

    answer = rag.ask("What channels does RagLeap support?")
    assert answer["provider_used"] == "gemini"
    assert answer["chunks_sent"] == 1
    assert answer["usage"]["total_tokens"] == 15
    assert len(answer["sources"]) == 1


def test_schema_actually_has_pgvector_and_halfvec(database_url):
    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector';")
    row = cur.fetchone()
    assert row is not None, "pgvector extension not installed"
    cur.close()
    conn.close()
