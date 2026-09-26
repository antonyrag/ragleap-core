package com.ragleap.rag.vectorstore;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for MilvusBackend - NOT live-verified against a real Milvus/Zilliz
 * Cloud instance, same honest caveat as the Python MilvusBackend and this
 * class's own javadoc. No Milvus instance was available on this VPS
 * (self-hosting requires etcd + MinIO + milvus-standalone, judged too
 * resource-risky on an already CPU-contended VPS).
 *
 * <p>Uses a local HTTP stub server (com.sun.net.httpserver.HttpServer),
 * matching this codebase's existing pattern for paid/unavailable
 * providers - this exercises the real HTTP request-building and
 * JSON-parsing code paths end-to-end against canned responses that match
 * Milvus's documented RESTful API v2 shapes (verified against
 * milvus.io/api-reference/restful/v2.4.x/ before writing this class),
 * rather than mocking an abstraction layer.
 */
class MilvusBackendTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final int DIM = 4;

    private HttpServer server;
    private String baseUrl;
    private final Map<String, Function<String, String>> responders = new ConcurrentHashMap<>();
    private final Map<String, String> lastRequestBodyByPath = new ConcurrentHashMap<>();

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        baseUrl = "http://localhost:" + server.getAddress().getPort();

        // Sensible defaults; individual tests override via responders.put(path, fn)
        responders.put("/v2/vectordb/collections/has", body -> "{\"code\":0,\"data\":{\"has\":false}}");
        responders.put("/v2/vectordb/collections/create", body -> "{\"code\":0,\"data\":{}}");
        responders.put("/v2/vectordb/entities/insert", body -> "{\"code\":0,\"data\":{\"insertCount\":1,\"insertIds\":[]}}");
        responders.put("/v2/vectordb/entities/search", body -> "{\"code\":0,\"data\":[]}");
        responders.put("/v2/vectordb/entities/delete", body -> "{\"code\":0,\"data\":{}}");

        server.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            lastRequestBodyByPath.put(path, requestBody);

            Function<String, String> responder = responders.get(path);
            String responseBody = responder != null ? responder.apply(requestBody) : "{\"code\":0,\"data\":{}}";
            byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);

            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });
        server.start();
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    private MilvusBackend newBackend(Path tempDir) throws SQLException {
        return new MilvusBackend(tempDir.resolve("mv_data").toString(), baseUrl, null, "ragleap_java_test");
    }

    private static List<Double> vec(double... vals) {
        Double[] boxed = new Double[vals.length];
        for (int i = 0; i < vals.length; i++) boxed[i] = vals[i];
        return List.of(boxed);
    }

    @Test
    void requiresPersistDirectory() {
        assertThrows(IllegalArgumentException.class, () -> new MilvusBackend("", baseUrl));
    }

    @Test
    void requiresUri(@TempDir Path tempDir) {
        assertThrows(IllegalArgumentException.class, () ->
                new MilvusBackend(tempDir.resolve("mv").toString(), null, null, null));
    }

    @Test
    void vectorKeyConstruction(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertEquals("doc1:0", backend.vectorKey("doc1", 0));
        // Unlike Pinecone/Qdrant/Weaviate, Milvus uses the raw vector_key
        // directly as its VarChar primary key - no UUID indirection.
        backend.close();
    }

    @Test
    void buildFilterExprSingleCondition(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertEquals("tenant == \"acme\"", backend.buildFilterExpr(Map.of("tenant", "acme")));
        backend.close();
    }

    @Test
    void buildFilterExprMultipleConditionsAnded(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        Map<String, Object> filter = new HashMap<>();
        filter.put("tenant", "acme");
        filter.put("region", "us");
        String expr = backend.buildFilterExpr(filter);
        assertTrue(expr.contains(" and "));
        assertTrue(expr.contains("tenant == \"acme\""));
        assertTrue(expr.contains("region == \"us\""));
        backend.close();
    }

    @Test
    void buildFilterExprNumericValueNotQuoted(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertEquals("chunk_index == 5", backend.buildFilterExpr(Map.of("chunk_index", 5)));
        backend.close();
    }

    @Test
    void buildFilterExprEmptyWhenNoFilter(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertEquals("", backend.buildFilterExpr(null));
        assertEquals("", backend.buildFilterExpr(Map.of()));
        backend.close();
    }

    @Test
    void initSchemaChecksHasThenCreatesWhenMissing(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        String createBody = lastRequestBodyByPath.get("/v2/vectordb/collections/create");
        assertTrue(createBody != null && createBody.contains("\"dimension\":4"));
        assertTrue(createBody.contains("\"idType\":\"VarChar\""));
        assertTrue(createBody.contains("\"metricType\":\"COSINE\""));
        backend.close();
    }

    @Test
    void initSchemaSkipsCreateWhenCollectionAlreadyExists(@TempDir Path tempDir) throws SQLException {
        responders.put("/v2/vectordb/collections/has", body -> "{\"code\":0,\"data\":{\"has\":true}}");
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        assertFalse(lastRequestBodyByPath.containsKey("/v2/vectordb/collections/create"));
        backend.close();
    }

    @Test
    void insertChunkSendsCorrectRequestBody(@TempDir Path tempDir) throws Exception {
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "chunk text", 5, vec(1, 0, 0, 0), Map.of("tenant", "acme"));

        String insertBody = lastRequestBodyByPath.get("/v2/vectordb/entities/insert");
        JsonNode parsed = MAPPER.readTree(insertBody);
        JsonNode row = parsed.path("data").get(0);
        assertEquals("doc1:0", row.path("id").asText());
        assertEquals("acme", row.path("tenant").asText());
        assertEquals(4, row.path("vector").size());
        backend.close();
    }

    @Test
    void searchDenseSkipsOrphanedHits(@TempDir Path tempDir) throws SQLException {
        responders.put("/v2/vectordb/entities/search",
                body -> "{\"code\":0,\"data\":[{\"id\":\"orphaned-not-in-sqlite\",\"distance\":0.5}]}");

        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        List<SearchResult> results = backend.searchDense(vec(0.1, 0.2, 0.3, 0.4), 5, null);
        assertTrue(results.isEmpty());
        backend.close();
    }

    @Test
    void searchDenseNormalizesCosineSimilarityToUnitRange(@TempDir Path tempDir) throws SQLException {
        // Regression test for the cosine normalization: Milvus with
        // metricType COSINE returns raw similarity in [-1, 1] per its own
        // documentation. This confirms the (x + 1) / 2 transform - not
        // live-verified against a real server, but the same formula
        // already confirmed live against Qdrant's identical COSINE
        // behavior elsewhere in this codebase.
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "identical vector", 3, vec(1, 0, 0, 0), Map.of());
        backend.insertChunk("doc1", "test.txt", 1, "orthogonal vector", 3, vec(0, 1, 0, 0), Map.of());
        backend.insertChunk("doc1", "test.txt", 2, "opposite vector", 3, vec(-1, 0, 0, 0), Map.of());

        responders.put("/v2/vectordb/entities/search", body -> "{\"code\":0,\"data\":["
                + "{\"id\":\"doc1:0\",\"distance\":1.0},"
                + "{\"id\":\"doc1:1\",\"distance\":0.0},"
                + "{\"id\":\"doc1:2\",\"distance\":-1.0}"
                + "]}");

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0), 5, null);

        Map<String, Double> scoreByText = new HashMap<>();
        for (SearchResult r : results) {
            scoreByText.put(r.text(), r.similarityScore());
        }

        assertEquals(1.0, scoreByText.get("identical vector"), 0.001);
        assertEquals(0.5, scoreByText.get("orthogonal vector"), 0.001);
        assertEquals(0.0, scoreByText.get("opposite vector"), 0.001);
        backend.close();
    }

    @Test
    void deleteDocumentSendsFilterWithVectorKeys(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "text", 3, vec(1, 0, 0, 0), Map.of());

        boolean deleted = backend.deleteDocument("doc1");

        assertTrue(deleted);
        // deleteBody is the raw JSON wire text; the "filter" field's value
        // is itself a JSON string containing quotes, so Jackson escapes
        // them (\" not "). Check the substring content, not a specific
        // quoting form, so this doesn't depend on that escaping detail.
        String deleteBody = lastRequestBodyByPath.get("/v2/vectordb/entities/delete");
        assertTrue(deleteBody.contains("doc1:0"));
        assertTrue(deleteBody.contains("id in ["));
        backend.close();
    }

    @Test
    void deleteUnknownDocumentReturnsFalse(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertFalse(backend.deleteDocument("nonexistent-id"));
        backend.close();
    }

    @Test
    void supportsSparseIsFalse(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        assertFalse(backend.supportsSparse());
        backend.close();
    }

    @Test
    void dimensionMismatchGuardReturnsEmpty(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        List<SearchResult> results = backend.searchDense(vec(1, 0), 5, null);
        assertTrue(results.isEmpty());
        backend.close();
    }

    @Test
    void getDocumentFilenameReturnsFilenameOrEmpty(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        backend.insertDocument("doc-x", "x.txt", Map.of());

        assertEquals("x.txt", backend.getDocumentFilename("doc-x").orElseThrow());
        assertTrue(backend.getDocumentFilename("nonexistent").isEmpty());
        backend.close();
    }

    @Test
    void listDocumentsAndPagination(@TempDir Path tempDir) throws SQLException {
        MilvusBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.insertDocument("doc-a", "a.txt", Map.of());
        backend.insertChunk("doc-a", "a.txt", 0, "text a", 3, vec(1, 0, 0, 0), Map.of());
        backend.insertDocument("doc-b", "b.txt", Map.of());
        backend.insertChunk("doc-b", "b.txt", 0, "text b", 3, vec(0, 1, 0, 0), Map.of());

        List<DocumentSummary> all = backend.listDocuments(10, 0);
        assertEquals(2, all.size());

        List<DocumentSummary> page1 = backend.listDocuments(1, 0);
        List<DocumentSummary> page2 = backend.listDocuments(1, 1);
        assertEquals(1, page1.size());
        assertEquals(1, page2.size());
        backend.close();
    }
}
