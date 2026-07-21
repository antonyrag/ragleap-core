"""
Database schema management for ragleap-rag.
"""
import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL_TEMPLATE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_name TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER,
    embedding vector({dimensions}),
    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    text_search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb;

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw ((embedding::halfvec({dimensions})) halfvec_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_text_search_idx
    ON chunks USING GIN (text_search_vector);

CREATE INDEX IF NOT EXISTS chunks_metadata_idx
    ON chunks USING GIN (metadata);

CREATE INDEX IF NOT EXISTS documents_metadata_idx
    ON documents USING GIN (metadata);

CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversation_messages_session_idx
    ON conversation_messages (session_id, created_at);
"""


def get_schema_sql(dimensions: int = 3072) -> str:
    """Return the DDL for the given embedding dimensionality."""
    return SCHEMA_SQL_TEMPLATE.format(dimensions=dimensions)


def init_schema(database_url: str, dimensions: int = 3072) -> None:
    """
    Create the required tables/indexes in the given database if they
    don't already exist. Safe to call repeatedly (idempotent —
    everything uses IF NOT EXISTS).
    """
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        cur.execute(get_schema_sql(dimensions))
        conn.commit()
        cur.close()
        logger.info(f"Schema initialized (embedding dimensions={dimensions})")
    finally:
        conn.close()
