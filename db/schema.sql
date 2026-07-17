-- RagLeap Core database schema
-- Requires the pgvector extension (bundled in the pgvector/pgvector Docker image)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_name TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER,
    embedding vector(3072),
    detected_language TEXT,
    language_confidence REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- pgvector's HNSW index has a hard 2000-dimension limit for standard `vector`,
-- but Gemini's gemini-embedding-001 produces 3072-dim vectors. We cast to
-- halfvec(3072) (half-precision, pgvector >= 0.7.0) to build the index within
-- that limit, matching the same workaround used in RagLeap's production schema.
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);

-- Full-text search support for hybrid (dense + sparse) retrieval.
-- Generated column stays in sync automatically on insert/update.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

CREATE INDEX IF NOT EXISTS chunks_text_search_idx
    ON chunks USING GIN (text_search_vector);

-- Integrations: external data sources (databases, CRMs, SaaS APIs) that can
-- sync per-user context into RAG responses. Single-tenant — no workspace scoping.
CREATE TABLE IF NOT EXISTS data_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,

    -- Connection details (encrypted at the application layer via Fernet
    -- before being written here — never store plaintext credentials)
    connection_string TEXT,
    api_endpoint TEXT,
    api_key TEXT,
    api_headers JSONB DEFAULT '{}',

    -- Query configuration
    query_template TEXT,
    field_mappings JSONB DEFAULT '{}',
    user_identifier_field TEXT NOT NULL DEFAULT 'user_id',
    documents_table_name TEXT NOT NULL DEFAULT 'documents',

    -- Sync configuration
    sync_interval_minutes INTEGER NOT NULL DEFAULT 360,
    last_sync_at TIMESTAMPTZ,
    last_sync_status TEXT NOT NULL DEFAULT 'pending',
    last_sync_error TEXT,
    last_sync_record_count INTEGER NOT NULL DEFAULT 0,

    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Customer/user context synced from external data sources, used to
-- personalize RAG responses.
CREATE TABLE IF NOT EXISTS synced_context_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data_source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    user_identifier TEXT NOT NULL,
    context_data JSONB NOT NULL DEFAULT '{}',
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_updated_at TIMESTAMPTZ,
    UNIQUE (data_source_id, user_identifier)
);

CREATE INDEX IF NOT EXISTS synced_context_data_lookup_idx
    ON synced_context_data (data_source_id, user_identifier);

