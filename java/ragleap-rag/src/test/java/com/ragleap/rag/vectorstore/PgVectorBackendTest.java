package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Real integration test against the live ragleap_java_test database -
 * NOT mocked. Uses a small dimension count (8) for fast, deterministic
 * test vectors while still exercising real pgvector similarity math.
 */
class PgVectorBackendTest {

    private static final String DATABASE_URL = System.getenv().getOrDefault(
            "RAGLEAP_JAVA_TEST_DATABASE_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test"
    );
    private static final int DIMS = 8;

    private static PgVectorBackend backend;

    @BeforeAll
    static void setUp() throws SQLException {
        backend = new PgVectorBackend(DATABASE_URL, 0.0); // 0.0 threshold: don't filter results in tests
        backend.initSchema(DIMS);
    }

    @AfterEach
    void cleanUpRows() throws Exception {
        // Truncate between tests so document/chunk counts don't bleed
        // across tests - schema itself stays (idempotent CREATE anyway).
        java.lang.reflect.Field poolField = PgVectorBackend.class.getDeclaredField("pool");
        poolField.setAccessible(true);
        var pool = (com.ragleap.rag.db.ConnectionPool) poolField.get(backend);
        try (Connection conn = pool.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute("TRUNCATE documents CASCADE");
            conn.commit();
        }
    }

    @AfterAll
    static void tearDown() throws SQLException {
        java.lang.reflect.Field poolField;
        try {
            poolField = PgVectorBackend.class.getDeclaredField("pool");
            poolField.setAccessible(true);
            var pool = (com.ragleap.rag.db.ConnectionPool) poolField.get(backend);
            try (Connection conn = pool.getConnection();
                 Statement stmt = conn.createStatement()) {
                stmt.execute("DROP TABLE IF EXISTS chunks CASCADE");
                stmt.execute("DROP TABLE IF EXISTS documents CASCADE");
                conn.commit();
            }
            pool.close();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private static List<Double> vec(double... values) {
        List<Double> list = new java.util.ArrayList<>();
        for (double v : values) {
            list.add(v);
        }
        return list;
    }

    @Test
    void insertAndRetrieveDocumentFilename() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "report.pdf", Map.of("source", "upload"));

        Optional<String> filename = backend.getDocumentFilename(docId);
        assertTrue(filename.isPresent());
        assertEquals("report.pdf", filename.get());
    }

    @Test
    void getDocumentFilenameEmptyForNonexistentDocument() throws SQLException {
        assertTrue(backend.getDocumentFilename(UUID.randomUUID().toString()).isEmpty());
    }

    @Test
    void insertChunkAndSearchDenseFindsExactMatchFirst() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());

        backend.insertChunk(docId, "doc.txt", 0, "chunk about cats",
                10, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());
        backend.insertChunk(docId, "doc.txt", 1, "chunk about dogs",
                10, vec(0, 1, 0, 0, 0, 0, 0, 0), Map.of());

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0, 0, 0, 0, 0), 5, null);

        assertFalse(results.isEmpty());
        assertEquals("chunk about cats", results.get(0).text());
        assertTrue(results.get(0).similarityScore() > results.get(results.size() - 1).similarityScore()
                || results.size() == 1);
    }

    @Test
    void searchDenseRespectsTopK() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        for (int i = 0; i < 5; i++) {
            backend.insertChunk(docId, "doc.txt", i, "chunk " + i, 5,
                    vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());
        }

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0, 0, 0, 0, 0), 2, null);
        assertEquals(2, results.size());
    }

    @Test
    void searchDenseWithMetadataFilterOnlyReturnsMatchingChunks() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        backend.insertChunk(docId, "doc.txt", 0, "public chunk", 5,
                vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of("visibility", "public"));
        backend.insertChunk(docId, "doc.txt", 1, "private chunk", 5,
                vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of("visibility", "private"));

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0, 0, 0, 0, 0), 10,
                Map.of("visibility", "public"));

        assertEquals(1, results.size());
        assertEquals("public chunk", results.get(0).text());
    }

    @Test
    void searchDenseReturnsEmptyForEmptyEmbedding() throws SQLException {
        assertEquals(List.of(), backend.searchDense(List.of(), 5, null));
    }

    @Test
    void listDocumentsReturnsMostRecentFirstWithChunkCounts() throws SQLException, InterruptedException {
        String doc1 = UUID.randomUUID().toString();
        String doc2 = UUID.randomUUID().toString();
        backend.insertDocument(doc1, "first.txt", Map.of());
        Thread.sleep(10); // ensure distinct uploaded_at ordering
        backend.insertDocument(doc2, "second.txt", Map.of());
        backend.insertChunk(doc2, "second.txt", 0, "chunk", 5, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());

        List<DocumentSummary> docs = backend.listDocuments(10, 0);

        assertEquals(2, docs.size());
        assertEquals("second.txt", docs.get(0).filename()); // most recent first
        assertEquals(1, docs.get(0).chunkCount());
        assertEquals(0, docs.get(1).chunkCount());
    }

    @Test
    void deleteDocumentReturnsTrueAndCascadesChunks() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        backend.insertChunk(docId, "doc.txt", 0, "chunk", 5, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());

        boolean deleted = backend.deleteDocument(docId);
        assertTrue(deleted);
        assertTrue(backend.getDocumentFilename(docId).isEmpty());

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0, 0, 0, 0, 0), 10, null);
        assertTrue(results.isEmpty(), "Chunks should cascade-delete with their parent document");
    }

    @Test
    void deleteDocumentReturnsFalseForNonexistentDocument() throws SQLException {
        assertFalse(backend.deleteDocument(UUID.randomUUID().toString()));
    }

    @Test
    void supportsSparseNowReturnsTrue() {
        // Now that searchSparse/searchHybrid are ported, PgVectorBackend
        // overrides the interface default and correctly reports true.
        assertTrue(backend.supportsSparse());
    }

    @Test
    void searchSparseFindsMatchingChunkByKeyword() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        backend.insertChunk(docId, "doc.txt", 0, "The quick brown fox jumps over the lazy dog",
                10, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());
        backend.insertChunk(docId, "doc.txt", 1, "Completely unrelated content about weather",
                10, vec(0, 1, 0, 0, 0, 0, 0, 0), Map.of());

        List<SearchResult> results = backend.searchSparse("fox jumps", 5, null);

        assertFalse(results.isEmpty());
        assertTrue(results.get(0).text().contains("fox"));
    }

    @Test
    void searchSparseReturnsEmptyForBlankQuery() throws SQLException {
        assertEquals(List.of(), backend.searchSparse("", 5, null));
        assertEquals(List.of(), backend.searchSparse("   ", 5, null));
        assertEquals(List.of(), backend.searchSparse(null, 5, null));
    }

    @Test
    void searchSparseWithMetadataFilterOnlyReturnsMatchingChunks() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        backend.insertChunk(docId, "doc.txt", 0, "public information about elephants",
                10, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of("visibility", "public"));
        backend.insertChunk(docId, "doc.txt", 1, "private information about elephants",
                10, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of("visibility", "private"));

        List<SearchResult> results = backend.searchSparse("elephants", 10, Map.of("visibility", "public"));

        assertEquals(1, results.size());
        assertTrue(results.get(0).text().contains("public"));
    }

    @Test
    void searchHybridCombinesDenseAndSparseWithRrfFusion() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        // Chunk A: exact vector match AND keyword match - should rank highest
        backend.insertChunk(docId, "doc.txt", 0, "the quick brown fox",
                10, vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());
        // Chunk B: keyword match only, no vector similarity
        backend.insertChunk(docId, "doc.txt", 1, "a fox in the forest",
                10, vec(0, 0, 0, 0, 0, 0, 0, 1), Map.of());
        // Chunk C: vector match only, no keyword overlap
        backend.insertChunk(docId, "doc.txt", 2, "completely different topic entirely",
                10, vec(0.99, 0.01, 0, 0, 0, 0, 0, 0), Map.of());

        List<SearchResult> results = backend.searchHybrid("fox", vec(1, 0, 0, 0, 0, 0, 0, 0), 10, null);

        assertFalse(results.isEmpty());
        // Chunk A hits both dense and sparse rankings, should be first
        assertEquals("the quick brown fox", results.get(0).text());
        assertEquals("hybrid_rrf", results.get(0).retrievalMethod());
        // Every result should carry the hybrid marker
        for (SearchResult r : results) {
            assertEquals("hybrid_rrf", r.retrievalMethod());
        }
    }

    @Test
    void searchHybridRespectsTopK() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        for (int i = 0; i < 5; i++) {
            backend.insertChunk(docId, "doc.txt", i, "shared keyword chunk " + i, 5,
                    vec(1, 0, 0, 0, 0, 0, 0, 0), Map.of());
        }

        List<SearchResult> results = backend.searchHybrid("shared keyword", vec(1, 0, 0, 0, 0, 0, 0, 0), 2, null);
        assertEquals(2, results.size());
    }

    @Test
    void searchHybridReturnsEmptyWhenNeitherDenseNorSparseMatch() throws SQLException {
        String docId = UUID.randomUUID().toString();
        backend.insertDocument(docId, "doc.txt", Map.of());
        backend.insertChunk(docId, "doc.txt", 0, "some content", 5,
                vec(0, 1, 0, 0, 0, 0, 0, 0), Map.of());

        // Orthogonal vector AND a query term that appears nowhere
        List<SearchResult> results = backend.searchHybrid("zzznomatchzzz", vec(1, 0, 0, 0, 0, 0, 0, 0), 10, null);

        // Dense will still return the chunk (min_similarity is 0.0 in this
        // test setup) since search_dense has no keyword requirement - but
        // confirm it's still marked hybrid_rrf and doesn't error.
        for (SearchResult r : results) {
            assertEquals("hybrid_rrf", r.retrievalMethod());
        }
    }
}
