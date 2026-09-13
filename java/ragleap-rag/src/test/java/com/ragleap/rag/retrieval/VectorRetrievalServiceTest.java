package com.ragleap.rag.retrieval;

import com.ragleap.rag.db.ConnectionPool;
import com.ragleap.rag.schema.SchemaManager;
import com.ragleap.rag.vectorstore.SearchResult;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Types;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.StringJoiner;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Real integration test against the live ragleap_java_test database -
 * NOT mocked. Uses raw SQL to insert test data directly (bypassing
 * PgVectorBackend) since VectorRetrievalService operates on a raw
 * ConnectionPool, matching the Python source's actual structure.
 */
class VectorRetrievalServiceTest {

    private static final String DATABASE_URL = System.getenv().getOrDefault(
            "RAGLEAP_JAVA_TEST_DATABASE_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test"
    );
    private static final int DIMS = 8;

    private static ConnectionPool pool;
    private static VectorRetrievalService service;

    @BeforeAll
    static void setUp() throws SQLException {
        pool = new ConnectionPool(DATABASE_URL, 1, 10);
        SchemaManager.initCoreSchema(pool, DIMS);
        service = new VectorRetrievalService(pool, DIMS, 0.0); // 0.0 threshold: don't filter in tests
    }

    @AfterEach
    void cleanUpRows() throws SQLException {
        try (Connection conn = pool.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute("TRUNCATE documents CASCADE");
            conn.commit();
        }
    }

    @AfterAll
    static void tearDown() throws SQLException {
        try (Connection conn = pool.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute("DROP TABLE IF EXISTS chunks CASCADE");
            stmt.execute("DROP TABLE IF EXISTS documents CASCADE");
            conn.commit();
        }
        pool.close();
    }

    private static List<Double> vec(double... values) {
        List<Double> list = new ArrayList<>();
        for (double v : values) {
            list.add(v);
        }
        return list;
    }

    private static String insertDocument(String filename) throws SQLException {
        String docId = UUID.randomUUID().toString();
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "INSERT INTO documents (id, filename, metadata) VALUES (?, ?, '{}'::jsonb)")) {
            stmt.setObject(1, UUID.fromString(docId));
            stmt.setString(2, filename);
            stmt.executeUpdate();
            conn.commit();
        }
        return docId;
    }

    private static void insertChunk(String docId, String docName, int chunkIndex, String text,
                                      List<Double> embedding, String metadataJson) throws SQLException {
        StringJoiner joiner = new StringJoiner(",", "[", "]");
        for (Double v : embedding) {
            joiner.add(String.valueOf(v));
        }
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding, metadata) " +
                     "VALUES (?, ?, ?, ?, ?, ?::vector, ?::jsonb)")) {
            stmt.setObject(1, UUID.fromString(docId));
            stmt.setString(2, docName);
            stmt.setInt(3, chunkIndex);
            stmt.setString(4, text);
            stmt.setInt(5, 5);
            stmt.setString(6, joiner.toString());
            stmt.setString(7, metadataJson != null ? metadataJson : "{}");
            stmt.executeUpdate();
            conn.commit();
        }
    }

    @Test
    void searchSimilarChunksReturnsEmptyForEmptyEmbedding() throws SQLException {
        assertEquals(List.of(), service.searchSimilarChunks(List.of(), 5, null, null));
    }

    @Test
    void searchSimilarChunksReturnsEmptyOnDimensionMismatch() throws SQLException {
        // Service configured for DIMS=8, but this embedding has only 3 -
        // must warn and return empty, NOT throw or attempt the query.
        // Distinct behavior from PgVectorBackend, which has no such check.
        List<SearchResult> results = service.searchSimilarChunks(vec(1, 0, 0), 5, null, null);
        assertEquals(List.of(), results);
    }

    @Test
    void searchSimilarChunksFindsExactMatchFirst() throws SQLException {
        String docId = insertDocument("doc.txt");
        insertChunk(docId, "doc.txt", 0, "about cats", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(docId, "doc.txt", 1, "about dogs", vec(0, 1, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchSimilarChunks(vec(1, 0, 0, 0, 0, 0, 0, 0), 5, null, null);

        assertFalse(results.isEmpty());
        assertEquals("about cats", results.get(0).text());
    }

    @Test
    void searchSimilarChunksFiltersByDocumentId() throws SQLException {
        String doc1 = insertDocument("doc1.txt");
        String doc2 = insertDocument("doc2.txt");
        insertChunk(doc1, "doc1.txt", 0, "chunk in doc1", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(doc2, "doc2.txt", 0, "chunk in doc2", vec(1, 0, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchSimilarChunks(vec(1, 0, 0, 0, 0, 0, 0, 0), 10, doc1, null);

        assertEquals(1, results.size());
        assertEquals("chunk in doc1", results.get(0).text());
    }

    @Test
    void searchSimilarChunksFiltersByMetadata() throws SQLException {
        String docId = insertDocument("doc.txt");
        insertChunk(docId, "doc.txt", 0, "public chunk", vec(1, 0, 0, 0, 0, 0, 0, 0), "{\"visibility\": \"public\"}");
        insertChunk(docId, "doc.txt", 1, "private chunk", vec(1, 0, 0, 0, 0, 0, 0, 0), "{\"visibility\": \"private\"}");

        List<SearchResult> results = service.searchSimilarChunks(
                vec(1, 0, 0, 0, 0, 0, 0, 0), 10, null, Map.of("visibility", "public"));

        assertEquals(1, results.size());
        assertEquals("public chunk", results.get(0).text());
    }

    @Test
    void searchSparseChunksReturnsEmptyForBlankQuery() throws SQLException {
        assertEquals(List.of(), service.searchSparseChunks("", 5, null, null));
        assertEquals(List.of(), service.searchSparseChunks(null, 5, null, null));
    }

    @Test
    void searchSparseChunksFindsKeywordMatch() throws SQLException {
        String docId = insertDocument("doc.txt");
        insertChunk(docId, "doc.txt", 0, "the quick brown fox", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(docId, "doc.txt", 1, "unrelated weather content", vec(0, 1, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchSparseChunks("fox", 5, null, null);

        assertFalse(results.isEmpty());
        assertTrue(results.get(0).text().contains("fox"));
    }

    @Test
    void searchSparseChunksFiltersByDocumentId() throws SQLException {
        String doc1 = insertDocument("doc1.txt");
        String doc2 = insertDocument("doc2.txt");
        insertChunk(doc1, "doc1.txt", 0, "shared keyword here", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(doc2, "doc2.txt", 0, "shared keyword here too", vec(1, 0, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchSparseChunks("keyword", 10, doc1, null);

        assertEquals(1, results.size());
    }

    @Test
    void searchHybridChunksCombinesDenseAndSparseWithRrf() throws SQLException {
        String docId = insertDocument("doc.txt");
        insertChunk(docId, "doc.txt", 0, "the quick brown fox", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(docId, "doc.txt", 1, "a fox in the forest", vec(0, 0, 0, 0, 0, 0, 0, 1), null);
        insertChunk(docId, "doc.txt", 2, "completely different topic", vec(0.99, 0.01, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchHybridChunks(
                "fox", vec(1, 0, 0, 0, 0, 0, 0, 0), 10, null, null);

        assertFalse(results.isEmpty());
        assertEquals("the quick brown fox", results.get(0).text());
        assertEquals("hybrid_rrf", results.get(0).retrievalMethod());
    }

    @Test
    void searchHybridChunksRespectsTopK() throws SQLException {
        String docId = insertDocument("doc.txt");
        for (int i = 0; i < 5; i++) {
            insertChunk(docId, "doc.txt", i, "shared keyword " + i, vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        }

        List<SearchResult> results = service.searchHybridChunks(
                "shared keyword", vec(1, 0, 0, 0, 0, 0, 0, 0), 2, null, null);

        assertEquals(2, results.size());
    }

    @Test
    void searchHybridChunksFiltersByDocumentId() throws SQLException {
        String doc1 = insertDocument("doc1.txt");
        String doc2 = insertDocument("doc2.txt");
        insertChunk(doc1, "doc1.txt", 0, "shared keyword", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertChunk(doc2, "doc2.txt", 0, "shared keyword", vec(1, 0, 0, 0, 0, 0, 0, 0), null);

        List<SearchResult> results = service.searchHybridChunks(
                "shared keyword", vec(1, 0, 0, 0, 0, 0, 0, 0), 10, doc1, null);

        assertEquals(1, results.size());
    }
}
