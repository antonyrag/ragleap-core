package com.ragleap.rag.schema;

import com.ragleap.rag.db.ConnectionPool;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Real integration test against the same live throwaway database used
 * by ConnectionPoolTest (ragleap_java_test) - not mocked. Verifies the
 * actual DDL runs successfully against real Postgres with the real
 * pgvector extension, not just that the SQL string looks right.
 */
class SchemaManagerTest {

    private static final String DATABASE_URL = System.getenv().getOrDefault(
            "RAGLEAP_JAVA_TEST_DATABASE_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test"
    );

    private static ConnectionPool pool;

    @BeforeAll
    static void setUpPool() {
        pool = new ConnectionPool(DATABASE_URL, 1, 5);
    }

    @AfterAll
    static void tearDownPool() throws SQLException {
        // Clean up tables this test creates, so repeated runs stay idempotent
        // and don't leave state for PgVectorBackendTest to trip over.
        try (Connection conn = pool.getConnection()) {
            try (Statement stmt = conn.createStatement()) {
                stmt.execute("DROP TABLE IF EXISTS conversation_messages CASCADE");
                stmt.execute("DROP TABLE IF EXISTS conversations CASCADE");
                stmt.execute("DROP TABLE IF EXISTS chunks CASCADE");
                stmt.execute("DROP TABLE IF EXISTS documents CASCADE");
            }
            conn.commit();
        }
        pool.close();
    }

    @Test
    void getCoreSchemaSqlInterpolatesDimensionsIntoBothVectorAndHalfvecCasts() {
        String sql = SchemaManager.getCoreSchemaSql(768);
        assertTrue(sql.contains("embedding vector(768)"));
        assertTrue(sql.contains("halfvec(768)"));
    }

    @Test
    void getSchemaSqlCombinesCoreAndMemory() {
        String combined = SchemaManager.getSchemaSql(768);
        assertTrue(combined.contains("CREATE TABLE IF NOT EXISTS documents"));
        assertTrue(combined.contains("CREATE TABLE IF NOT EXISTS conversations"));
    }

    @Test
    void initSchemaActuallyCreatesRealTablesOnRealPostgres() throws SQLException {
        SchemaManager.initSchema(pool, 8); // small dims for a fast test

        try (Connection conn = pool.getConnection()) {
            try (Statement stmt = conn.createStatement();
                 ResultSet rs = stmt.executeQuery(
                         "SELECT table_name FROM information_schema.tables " +
                         "WHERE table_schema = 'public' AND table_name IN " +
                         "('documents', 'chunks', 'conversations', 'conversation_messages')")) {
                int count = 0;
                while (rs.next()) {
                    count++;
                }
                assertEquals(4, count, "All 4 tables should exist after initSchema");
            }
        }
    }

    @Test
    void initSchemaIsIdempotentSafeToCallTwice() throws SQLException {
        assertDoesNotThrow(() -> {
            SchemaManager.initSchema(pool, 8);
            SchemaManager.initSchema(pool, 8); // second call must not fail
        });
    }

    @Test
    void hnswIndexIsActuallyCreatedOnRealPostgres() throws SQLException {
        SchemaManager.initCoreSchema(pool, 8);

        try (Connection conn = pool.getConnection()) {
            try (Statement stmt = conn.createStatement();
                 ResultSet rs = stmt.executeQuery(
                         "SELECT indexname FROM pg_indexes WHERE indexname = 'chunks_embedding_idx'")) {
                assertTrue(rs.next(), "HNSW index should exist on chunks.embedding");
            }
        }
    }
}
