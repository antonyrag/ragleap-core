package com.ragleap.rag.schema;

import com.ragleap.rag.db.ConnectionPool;

import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.logging.Logger;

/**
 * Database schema management for ragleap-rag. Java port of
 * ragleap-rag's schema.py.
 *
 * Split into two independent pieces, matching the Python source:
 * - Core schema (documents/chunks) - specific to PgVectorBackend.
 * - Memory schema (conversations/conversation_messages) - always
 *   Postgres regardless of vector backend choice, so stays independent.
 *
 * Deviation from Python, documented: the Python source opens its own
 * one-off psycopg2 connection via _run_sql() rather than using
 * ConnectionPool. This Java port routes schema initialization through
 * ConnectionPool instead - functionally equivalent (get a connection,
 * run DDL, done), and avoids duplicating the URL-parsing logic
 * ConnectionPool already has for a connection that's only used once.
 */
public final class SchemaManager {

    private static final Logger logger = Logger.getLogger(SchemaManager.class.getName());

    private SchemaManager() {
    }

    private static final String CORE_SCHEMA_SQL_TEMPLATE = """
            CREATE EXTENSION IF NOT EXISTS vector;

            CREATE TABLE IF NOT EXISTS documents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                filename TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                document_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                token_count INTEGER,
                embedding vector(%1$d),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                text_search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
            ALTER TABLE chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
                ON chunks USING hnsw ((embedding::halfvec(%1$d)) halfvec_cosine_ops);
            CREATE INDEX IF NOT EXISTS chunks_text_search_idx
                ON chunks USING GIN (text_search_vector);
            CREATE INDEX IF NOT EXISTS chunks_metadata_idx
                ON chunks USING GIN (metadata);
            CREATE INDEX IF NOT EXISTS documents_metadata_idx
                ON documents USING GIN (metadata);
            """;

    private static final String MEMORY_SCHEMA_SQL = """
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
            """;

    public static final int DEFAULT_DIMENSIONS = 3072;

    /** DDL for documents/chunks - the PgVectorBackend-specific pieces. */
    public static String getCoreSchemaSql(int dimensions) {
        return String.format(CORE_SCHEMA_SQL_TEMPLATE, dimensions);
    }

    /**
     * DDL for conversations/conversation_messages - always Postgres,
     * independent of which vector backend is in use.
     */
    public static String getMemorySchemaSql() {
        return MEMORY_SCHEMA_SQL;
    }

    /** Backward-compatible: both pieces combined, matching the old single-template behavior exactly. */
    public static String getSchemaSql(int dimensions) {
        return getCoreSchemaSql(dimensions) + getMemorySchemaSql();
    }

    private static void runSql(ConnectionPool pool, String sql) throws SQLException {
        try (Connection conn = pool.getConnection()) {
            try (Statement stmt = conn.createStatement()) {
                stmt.execute(sql);
            }
            conn.commit();
        }
    }

    /** Create/verify the documents/chunks tables. Idempotent. */
    public static void initCoreSchema(ConnectionPool pool, int dimensions) throws SQLException {
        runSql(pool, getCoreSchemaSql(dimensions));
        logger.info(() -> "Core schema initialized (embedding dimensions=" + dimensions + ")");
    }

    /**
     * Create/verify the conversations/conversation_messages tables.
     * Always Postgres, regardless of vector backend choice. Idempotent.
     */
    public static void initMemorySchema(ConnectionPool pool) throws SQLException {
        runSql(pool, getMemorySchemaSql());
        logger.info("Memory schema initialized");
    }

    /**
     * Backward-compatible: initializes both core and memory schema
     * together in one call, matching the old combined behavior exactly.
     * Safe to call repeatedly (idempotent - everything uses IF NOT EXISTS).
     */
    public static void initSchema(ConnectionPool pool, int dimensions) throws SQLException {
        initCoreSchema(pool, dimensions);
        initMemorySchema(pool);
    }
}
