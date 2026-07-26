"""
Database schema management for ragleap-rag.

Split into two independent pieces:
- Core schema (documents/chunks) - specific to PgVectorBackend, lives
  behind the VectorBackend interface now.
- Memory schema (conversations/conversation_messages) - conversation
  memory always requires Postgres regardless of which vector backend
  is chosen (FAISS, Pinecone, etc. only store vectors, not chat
  history), so this stays independent and is always initialized.

init_schema()/get_schema_sql() are kept as backward-compatible
wrappers that run both pieces together, exactly matching the old
combined behavior for anyone calling this module directly.
"""
import logging

logger = logging.getLogger(__name__)

CORE_SCHEMA_SQL_TEMPLATE = """
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
"""

MEMORY_SCHEMA_SQL = """
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


def get_core_schema_sql(dimensions: int = 3072) -> str:
    """DDL for documents/chunks - the PgVectorBackend-specific pieces."""
    return CORE_SCHEMA_SQL_TEMPLATE.format(dimensions=dimensions)


def get_memory_schema_sql() -> str:
    """DDL for conversations/conversation_messages - always Postgres,
    independent of which vector backend is in use."""
    return MEMORY_SCHEMA_SQL


def get_schema_sql(dimensions: int = 3072) -> str:
    """Backward-compatible: both pieces combined, matching the old
    single-template behavior exactly."""
    return get_core_schema_sql(dimensions) + get_memory_schema_sql()


def _run_sql(database_url: str, sql: str) -> None:
    import psycopg2
    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def init_core_schema(database_url: str, dimensions: int = 3072) -> None:
    """Create/verify the documents/chunks tables. Idempotent."""
    _run_sql(database_url, get_core_schema_sql(dimensions))
    logger.info(f"Core schema initialized (embedding dimensions={dimensions})")


def init_memory_schema(database_url: str) -> None:
    """Create/verify the conversations/conversation_messages tables.
    Always Postgres, regardless of vector backend choice. Idempotent."""
    _run_sql(database_url, get_memory_schema_sql())
    logger.info("Memory schema initialized")


def init_schema(database_url: str, dimensions: int = 3072) -> None:
    """
    Backward-compatible: initializes both core and memory schema
    together in one call, matching the old combined behavior exactly.
    Safe to call repeatedly (idempotent - everything uses IF NOT EXISTS).
    """
    init_core_schema(database_url, dimensions)
    init_memory_schema(database_url)
