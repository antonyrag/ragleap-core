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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- pgvector's HNSW index has a hard 2000-dimension limit for standard `vector`,
-- but Gemini's gemini-embedding-001 produces 3072-dim vectors. We cast to
-- halfvec(3072) (half-precision, pgvector >= 0.7.0) to build the index within
-- that limit, matching the same workaround used in RagLeap's production schema.
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);
