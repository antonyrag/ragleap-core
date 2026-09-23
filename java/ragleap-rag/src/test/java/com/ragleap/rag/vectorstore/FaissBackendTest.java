package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Real tests for FaissBackend - genuine in-memory index + real SQLite
 * sidecar, no mocking of the backend itself. Scenarios are grounded in
 * the real Python test_faiss_backend.py, adapted to this port's
 * VectorBackend-level interface (there is no RagLeap-facade equivalent
 * ported to Java yet, so tests exercise insertDocument/insertChunk/
 * searchDense/etc. directly rather than an ask()/ingest_text() wrapper).
 *
 * <p>Note: the Python suite's update_document() test has no equivalent
 * here - update_document() is a RagLeap-facade method (delete + re-ingest),
 * not part of the VectorBackend interface this port implements.
 */
class FaissBackendTest {

    private static final int DIM = 8;

    private FaissBackend backend;

    @BeforeEach
    void setUp() throws SQLException {
        backend = new FaissBackend();
        backend.initSchema(DIM);
    }

    @AfterEach
    void tearDown() throws SQLException {
        backend.close();
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
    void insertAndSearchRoundtrip() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0, 0, 0, 0, 0);
        insertOneChunkDoc("doc-1", "apples.txt", embedding, null);

        List<SearchResult> results = backend.searchDense(embedding, 1, null);

        assertEquals(1, results.size());
        assertEquals("apples.txt", results.get(0).documentName());
        assertEquals("doc-1", results.get(0).documentId());
    }

    @Test
    void denseSearchFindsCorrectDocument() throws SQLException {
        List<Double> vecA = vec(1, 0, 0, 0, 0, 0, 0, 0);
        List<Double> vecB = vec(0, 1, 0, 0, 0, 0, 0, 0);
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
        List<Double> embedding = vec(0, 0, 1, 0, 0, 0, 0, 0);
        insertOneChunkDoc("doc-z", "zebras.txt", embedding, null);

        // VectorBackend's default searchHybrid() falls back to searchDense()
        // when supportsSparse() is false - exactly what we're proving here.
        List<SearchResult> hybridResults = backend.searchHybrid("zebras", embedding, 1, null);
        List<SearchResult> denseResults = backend.searchDense(embedding, 1, null);

        assertEquals(denseResults.size(), hybridResults.size());
        assertEquals(denseResults.get(0).documentName(), hybridResults.get(0).documentName());
    }

    @Test
    void listDocumentsReturnsAllInserted() throws SQLException {
        insertOneChunkDoc("doc-a", "a.txt", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertOneChunkDoc("doc-b", "b.txt", vec(0, 1, 0, 0, 0, 0, 0, 0), null);

        List<DocumentSummary> docs = backend.listDocuments(10, 0);

        assertEquals(2, docs.size());
        List<String> filenames = docs.stream().map(DocumentSummary::filename).toList();
        assertTrue(filenames.contains("a.txt"));
        assertTrue(filenames.contains("b.txt"));
    }

    @Test
    void listDocumentsPagination() throws SQLException {
        insertOneChunkDoc("doc-a", "a.txt", vec(1, 0, 0, 0, 0, 0, 0, 0), null);
        insertOneChunkDoc("doc-b", "b.txt", vec(0, 1, 0, 0, 0, 0, 0, 0), null);
        insertOneChunkDoc("doc-c", "c.txt", vec(0, 0, 1, 0, 0, 0, 0, 0), null);

        List<DocumentSummary> page1 = backend.listDocuments(2, 0);
        List<DocumentSummary> page2 = backend.listDocuments(2, 2);

        assertEquals(2, page1.size());
        assertEquals(1, page2.size());
    }

    @Test
    void deleteDocumentRemovesItAndItsVector() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0, 0, 0, 0, 0);
        backend.insertDocument("doc-temp", "temp.txt", Map.of());
        backend.insertChunk("doc-temp", "temp.txt", 0, "temporary content", 3, embedding, Map.of());

        boolean deleted = backend.deleteDocument("doc-temp");

        assertTrue(deleted);
        assertEquals(0, backend.listDocuments(10, 0).size());
        // Prove the vector itself was actually removed from the index,
        // not just the SQLite metadata row - the real point of a delete.
        assertEquals(0, backend.searchDense(embedding, 5, null).size());
    }

    @Test
    void deleteUnknownDocumentReturnsFalse() throws SQLException {
        assertFalse(backend.deleteDocument("nonexistent-id"));
    }

    @Test
    void metadataFilterPostFiltersCorrectly() throws SQLException {
        List<Double> embedding = vec(1, 0, 0, 0, 0, 0, 0, 0);
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
        // Schema initialized with DIM=8 in setUp(); querying with a
        // 4-dimension embedding should be rejected gracefully, not throw.
        List<Double> wrongDim = vec(1, 0, 0, 0);
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
    void persistenceAcrossBackendInstances(@TempDir Path tempDir) throws SQLException {
        String persistDir = tempDir.resolve("faiss_persist_test").toString();
        List<Double> embedding = vec(1, 0, 0, 0, 0, 0, 0, 0);

        FaissBackend backend1 = new FaissBackend(persistDir);
        backend1.initSchema(DIM);
        backend1.insertDocument("doc-p", "persisted.txt", Map.of());
        backend1.insertChunk("doc-p", "persisted.txt", 0, "This content should survive a restart.", 6, embedding, Map.of());
        backend1.close();

        // Fresh instance, same directory - simulates a process restart.
        FaissBackend backend2 = new FaissBackend(persistDir);
        backend2.initSchema(DIM);

        List<DocumentSummary> docs = backend2.listDocuments(10, 0);
        assertEquals(1, docs.size());
        assertEquals("persisted.txt", docs.get(0).filename());

        // Prove the vector index itself round-tripped through our custom
        // binary format, not just the SQLite metadata - this is the real
        // point of writing a custom persistence format at all.
        List<SearchResult> results = backend2.searchDense(embedding, 1, null);
        assertEquals(1, results.size());
        assertEquals("persisted.txt", results.get(0).documentName());

        backend2.close();
    }
}
