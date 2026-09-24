package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.api.io.TempDir;

import java.net.URI;
import java.time.Duration;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Real tests for QdrantBackend - genuine REST calls against a real,
 * already-running Qdrant instance (localhost:6333), not mocked. Stricter
 * than the Python suite (which mocks the client entirely), matching this
 * project's own "prove it, don't just claim it" standard.
 *
 * <p>Each test run uses its own randomly-suffixed collection, dropped in
 * tearDown() - this shares the Qdrant server with the colleague's
 * ragleap-vectorstores Python tests (running in the qdrant-vectorstores-test
 * container) without any risk of collision, since our collection namespace
 * never overlaps theirs.
 */
@EnabledIf("qdrantIsReachable")
class QdrantBackendTest {

    private static final String QDRANT_URL = "http://localhost:6333";
    private static final int DIM = 4;

    /**
     * Skips this entire test class when no Qdrant instance is reachable
     * at QDRANT_URL, rather than failing - this suite hits a real running
     * Qdrant instance (this project has no mocked-Qdrant-client fallback,
     * unlike the Python suite, which mocks the client entirely). Local/VPS
     * runs with Qdrant up execute for real; CI runners with no Qdrant
     * service configured skip cleanly instead of erroring on every test.
     */
    static boolean qdrantIsReachable() {
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(QDRANT_URL + "/")).GET().build();
            HttpResponse<Void> response = client.send(req, HttpResponse.BodyHandlers.discarding());
            return response.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    private QdrantBackend backend;
    private String collectionName;

    @BeforeEach
    void setUp(@TempDir Path tempDir) throws SQLException {
        collectionName = "ragleap_java_test_" + UUID.randomUUID().toString().substring(0, 8);
        backend = new QdrantBackend(tempDir.resolve("qd_data").toString(), QDRANT_URL, null, collectionName);
        backend.initSchema(DIM);
    }

    @AfterEach
    void tearDown() throws Exception {
        backend.close();
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(QDRANT_URL + "/collections/" + collectionName))
                .DELETE()
                .build();
        client.send(req, HttpResponse.BodyHandlers.discarding());
    }

    private static List<Double> vec(double... vals) {
        Double[] boxed = new Double[vals.length];
        for (int i = 0; i < vals.length; i++) boxed[i] = vals[i];
        return List.of(boxed);
    }

    private void insertOneChunkDoc(String docId, String filename, List<Double> embedding, Map<String, Object> chunkMeta) throws SQLException {
        backend.insertDocument(docId, filename, Map.of());
        backend.insertChunk(docId, filename, 0, "chunk text for " + filename, 5, embedding,
                chunkMeta != null ? chunkMeta : Map.of());
    }

    @Test
    void requiresPersistDirectory(@TempDir Path tempDir) {
        assertThrows(IllegalArgumentException.class, () -> new QdrantBackend("", QDRANT_URL));
    }

    @Test
    void requiresUrl(@TempDir Path tempDir) {
        assertThrows(IllegalArgumentException.class, () ->
                new QdrantBackend(tempDir.resolve("qd").toString(), null, null, null));
    }

    @Test
    void insertAndSearchRoundtrip() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0);
        insertOneChunkDoc("doc-1", "apples.txt", embedding, null);

        List<SearchResult> results = backend.searchDense(embedding, 1, null);

        assertEquals(1, results.size());
        assertEquals("apples.txt", results.get(0).documentName());
        assertEquals("doc-1", results.get(0).documentId());
    }

    @Test
    void denseSearchFindsCorrectDocument() throws SQLException {
        List<Double> vecA = vec(1, 0, 0, 0);
        List<Double> vecB = vec(0, 1, 0, 0);
        insertOneChunkDoc("doc-a", "a.txt", vecA, null);
        insertOneChunkDoc("doc-b", "b.txt", vecB, null);

        List<SearchResult> results = backend.searchDense(vecA, 1, null);

        assertEquals(1, results.size());
        assertEquals("a.txt", results.get(0).documentName());
    }

    @Test
    void doesNotSupportSparse() {
        assertFalse(backend.supportsSparse());
    }

    @Test
    void hybridModeGracefullyDegradesToDense() throws SQLException {
        List<Double> embedding = vec(0, 0, 1, 0);
        insertOneChunkDoc("doc-z", "zebras.txt", embedding, null);

        List<SearchResult> hybridResults = backend.searchHybrid("zebras", embedding, 1, null);
        List<SearchResult> denseResults = backend.searchDense(embedding, 1, null);

        assertEquals(denseResults.size(), hybridResults.size());
        assertEquals(denseResults.get(0).documentName(), hybridResults.get(0).documentName());
    }

    @Test
    void listDocumentsReturnsAllInserted() throws SQLException {
        insertOneChunkDoc("doc-a", "a.txt", vec(1, 0, 0, 0), null);
        insertOneChunkDoc("doc-b", "b.txt", vec(0, 1, 0, 0), null);

        List<DocumentSummary> docs = backend.listDocuments(10, 0);

        assertEquals(2, docs.size());
        List<String> filenames = docs.stream().map(DocumentSummary::filename).toList();
        assertTrue(filenames.contains("a.txt"));
        assertTrue(filenames.contains("b.txt"));
    }

    @Test
    void listDocumentsPagination() throws SQLException {
        insertOneChunkDoc("doc-a", "a.txt", vec(1, 0, 0, 0), null);
        insertOneChunkDoc("doc-b", "b.txt", vec(0, 1, 0, 0), null);
        insertOneChunkDoc("doc-c", "c.txt", vec(0, 0, 1, 0), null);

        List<DocumentSummary> page1 = backend.listDocuments(2, 0);
        List<DocumentSummary> page2 = backend.listDocuments(2, 2);

        assertEquals(2, page1.size());
        assertEquals(1, page2.size());
    }

    @Test
    void deleteDocumentRemovesItAndItsVector() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0);
        backend.insertDocument("doc-temp", "temp.txt", Map.of());
        backend.insertChunk("doc-temp", "temp.txt", 0, "temporary content", 3, embedding, Map.of());

        boolean deleted = backend.deleteDocument("doc-temp");

        assertTrue(deleted);
        assertEquals(0, backend.listDocuments(10, 0).size());
        // Prove the vector itself was actually removed from Qdrant, not
        // just the SQLite metadata row - the real point of a delete.
        assertEquals(0, backend.searchDense(embedding, 5, null).size());
    }

    @Test
    void deleteUnknownDocumentReturnsFalse() throws SQLException {
        assertFalse(backend.deleteDocument("nonexistent-id"));
    }

    @Test
    void metadataFilterFiltersServerSideCorrectly() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0);
        backend.insertDocument("doc-acme", "a.txt", Map.of());
        backend.insertChunk("doc-acme", "a.txt", 0, "Pricing content here.", 4, embedding, Map.of("tenant", "acme"));

        backend.insertDocument("doc-globex", "b.txt", Map.of());
        backend.insertChunk("doc-globex", "b.txt", 0, "Pricing content here too.", 4, embedding, Map.of("tenant", "globex"));

        Map<String, Object> filter = new HashMap<>();
        filter.put("tenant", "acme");
        List<SearchResult> results = backend.searchDense(embedding, 5, filter);

        assertEquals(1, results.size());
        assertEquals("a.txt", results.get(0).documentName());
    }

    @Test
    void dimensionMismatchGuardReturnsEmpty() throws SQLException {
        List<Double> wrongDim = vec(1, 0);
        List<SearchResult> results = backend.searchDense(wrongDim, 5, null);
        assertEquals(0, results.size());
    }

    @Test
    void getDocumentFilenameReturnsFilenameOrEmpty() throws SQLException {
        backend.insertDocument("doc-x", "x.txt", Map.of());

        assertEquals("x.txt", backend.getDocumentFilename("doc-x").orElseThrow());
        assertTrue(backend.getDocumentFilename("nonexistent").isEmpty());
    }

    @Test
    void similarityScoreNormalizedToUnitRange() throws SQLException {
        // Regression test for the real normalization bug already found and
        // fixed in the Python QdrantBackend: raw cosine in [-1, 1] must be
        // mapped to [0, 1] via (x + 1) / 2, matching pgvector's convention.
        // Identical vector -> score 1.0; orthogonal -> 0.5.
        List<Double> embedding = vec(1, 0, 0, 0);
        List<Double> orthogonal = vec(0, 1, 0, 0);
        insertOneChunkDoc("doc-identical", "identical.txt", embedding, null);
        insertOneChunkDoc("doc-orthogonal", "orthogonal.txt", orthogonal, null);

        List<SearchResult> results = backend.searchDense(embedding, 5, null);

        Map<String, Double> scoreByDoc = new HashMap<>();
        for (SearchResult r : results) {
            scoreByDoc.put(r.documentName(), r.similarityScore());
        }

        assertEquals(1.0, scoreByDoc.get("identical.txt"), 0.001);
        assertEquals(0.5, scoreByDoc.get("orthogonal.txt"), 0.001);
    }

    @Test
    void deterministicIdStableAcrossDeleteAndReinsert() throws SQLException {
        // Neither this backend nor the Python source support re-inserting
        // the same document_id+chunk_index while the row still exists
        // (both use a plain INSERT, not upsert) - that was never a
        // supported operation, so this instead proves the real property
        // deterministic IDs exist for: a document deleted and later
        // re-ingested with the same document_id+chunk_index gets back the
        // exact same Qdrant point ID, not a random new one.
        List<Double> embedding = vec(1, 0, 0, 0);

        backend.insertDocument("doc-stable", "stable.txt", Map.of());
        backend.insertChunk("doc-stable", "stable.txt", 0, "version one", 3, embedding, Map.of());
        String firstId = backend.searchDense(embedding, 1, null).get(0).chunkId();

        backend.deleteDocument("doc-stable");

        backend.insertDocument("doc-stable", "stable.txt", Map.of());
        backend.insertChunk("doc-stable", "stable.txt", 0, "version two", 3, embedding, Map.of());
        String secondId = backend.searchDense(embedding, 1, null).get(0).chunkId();

        assertEquals(firstId, secondId);
    }

    @Test
    void persistenceAcrossBackendInstances(@TempDir Path tempDir) throws SQLException {
        String persistDir = tempDir.resolve("qd_persist_test").toString();
        String sharedCollection = "ragleap_java_persist_test_" + UUID.randomUUID().toString().substring(0, 8);
        List<Double> embedding = vec(1, 0, 0, 0);

        QdrantBackend backend1 = new QdrantBackend(persistDir, QDRANT_URL, null, sharedCollection);
        backend1.initSchema(DIM);
        backend1.insertDocument("doc-p", "persisted.txt", Map.of());
        backend1.insertChunk("doc-p", "persisted.txt", 0, "This content should survive a restart.", 6, embedding, Map.of());
        backend1.close();

        // Fresh instance, same persist directory and collection - simulates
        // a process restart against the same remote Qdrant collection.
        QdrantBackend backend2 = new QdrantBackend(persistDir, QDRANT_URL, null, sharedCollection);
        backend2.initSchema(DIM);

        List<DocumentSummary> docs = backend2.listDocuments(10, 0);
        assertEquals(1, docs.size());
        assertEquals("persisted.txt", docs.get(0).filename());

        List<SearchResult> results = backend2.searchDense(embedding, 1, null);
        assertEquals(1, results.size());
        assertEquals("persisted.txt", results.get(0).documentName());

        // Manual cleanup since this test doesn't use the class's collectionName field
        backend2.close();
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(QDRANT_URL + "/collections/" + sharedCollection))
                .DELETE()
                .build();
        try {
            client.send(req, HttpResponse.BodyHandlers.discarding());
        } catch (Exception ignored) {
        }
    }
}
