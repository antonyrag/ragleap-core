package com.ragleap.rag.vectorstore;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
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
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for PineconeBackend - NOT live-verified against a real Pinecone
 * account (see the class's own javadoc for exactly what was and was not
 * confirmed). Uses a local HTTP stub server serving both the Pinecone
 * control plane ({@code /indexes}) and the per-index data plane
 * ({@code /vectors/upsert}, {@code /query}, {@code /vectors/delete}), with
 * canned responses matching the documented API shapes. This exercises the
 * real HTTP request-building and JSON-parsing code paths, same approach as
 * MilvusBackendTest.
 */
class PineconeBackendTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final int DIM = 4;
    private static final String INDEX = "ragleap-java-test";

    private HttpServer server;
    private String baseUrl;
    private final Map<String, Function<String, String>> responders = new ConcurrentHashMap<>();
    private final Map<String, Integer> statusByKey = new ConcurrentHashMap<>();
    private final Map<String, String> lastBodyByKey = new ConcurrentHashMap<>();
    private final Map<String, Headers> lastHeadersByKey = new ConcurrentHashMap<>();

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        baseUrl = "http://localhost:" + server.getAddress().getPort();

        responders.put("GET /indexes", body -> "{\"indexes\":[]}");
        responders.put("POST /indexes", body -> "{\"name\":\"" + INDEX + "\"}");
        responders.put("GET /indexes/" + INDEX, body ->
                "{\"name\":\"" + INDEX + "\",\"host\":\"" + baseUrl + "\",\"status\":{\"ready\":true,\"state\":\"Ready\"}}");
        responders.put("POST /vectors/upsert", body -> "{\"upsertedCount\":1}");
        responders.put("POST /query", body -> "{\"matches\":[],\"namespace\":\"\",\"usage\":{\"readUnits\":1}}");
        responders.put("POST /vectors/delete", body -> "{}");

        server.createContext("/", exchange -> {
            String key = exchange.getRequestMethod() + " " + exchange.getRequestURI().getPath();
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            lastBodyByKey.put(key, requestBody);
            lastHeadersByKey.put(key, exchange.getRequestHeaders());

            Function<String, String> responder = responders.get(key);
            String responseBody = responder != null ? responder.apply(requestBody) : "{}";
            int status = statusByKey.getOrDefault(key, 200);
            byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);

            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
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

    private PineconeBackend newBackend(Path tempDir) throws SQLException {
        return new PineconeBackend(tempDir.resolve("pc_data").toString(), "test-key", INDEX,
                "aws", "us-east-1", baseUrl, 10, 2000);
    }

    private static List<Double> vec(double... vals) {
        Double[] boxed = new Double[vals.length];
        for (int i = 0; i < vals.length; i++) boxed[i] = vals[i];
        return List.of(boxed);
    }

    @Test
    void requiresPersistDirectory() {
        assertThrows(IllegalArgumentException.class, () -> new PineconeBackend("", "test-key"));
    }

    @Test
    void requiresApiKey(@TempDir Path tempDir) {
        Assumptions.assumeTrue(System.getenv("PINECONE_API_KEY") == null,
                "PINECONE_API_KEY is set in this environment, so the missing-key path cannot be exercised");
        assertThrows(IllegalArgumentException.class, () ->
                new PineconeBackend(tempDir.resolve("pc").toString(), null));
    }

    @Test
    void vectorIdConstruction(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        assertEquals("doc1:0", backend.vectorId("doc1", 0));
        assertEquals("doc1:5", backend.vectorId("doc1", 5));
        backend.close();
    }

    @Test
    void buildFilterTranslatesToPineconeEqSyntax(@TempDir Path tempDir) throws Exception {
        PineconeBackend backend = newBackend(tempDir);
        Map<String, Object> filter = new HashMap<>();
        filter.put("tenant", "acme");
        filter.put("region", "us");

        JsonNode result = backend.buildFilter(filter);
        assertEquals("acme", result.path("tenant").path("$eq").asText());
        assertEquals("us", result.path("region").path("$eq").asText());
        backend.close();
    }

    @Test
    void buildFilterNullWhenNoFilter(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        assertNull(backend.buildFilter(null));
        assertNull(backend.buildFilter(Map.of()));
        backend.close();
    }

    @Test
    void initSchemaCreatesIndexWhenMissingWithPinnedVersionAndAuthHeaders(@TempDir Path tempDir) throws Exception {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        JsonNode create = MAPPER.readTree(lastBodyByKey.get("POST /indexes"));
        assertEquals(INDEX, create.path("name").asText());
        assertEquals(4, create.path("dimension").asInt());
        assertEquals("cosine", create.path("metric").asText());
        assertEquals("aws", create.path("spec").path("serverless").path("cloud").asText());
        assertEquals("us-east-1", create.path("spec").path("serverless").path("region").asText());

        Headers headers = lastHeadersByKey.get("GET /indexes");
        assertEquals("test-key", headers.getFirst("Api-Key"));
        assertEquals("2026-04", headers.getFirst("X-Pinecone-Api-Version"));
        backend.close();
    }

    @Test
    void initSchemaSkipsCreateWhenIndexAlreadyExists(@TempDir Path tempDir) throws SQLException {
        responders.put("GET /indexes", body -> "{\"indexes\":[{\"name\":\"" + INDEX + "\"}]}");
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        assertFalse(lastBodyByKey.containsKey("POST /indexes"));
        backend.close();
    }

    @Test
    void initSchemaPollsUntilIndexReady(@TempDir Path tempDir) throws SQLException {
        AtomicInteger describeCalls = new AtomicInteger();
        responders.put("GET /indexes/" + INDEX, body -> {
            boolean ready = describeCalls.incrementAndGet() > 2;
            return "{\"name\":\"" + INDEX + "\",\"host\":\"" + baseUrl + "\",\"status\":{\"ready\":" + ready + "}}";
        });

        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        assertTrue(describeCalls.get() >= 3, "expected at least 3 describe calls, got " + describeCalls.get());
        backend.close();
    }

    @Test
    void insertChunkUpsertsCorrectBodyAndStoresTextInSqlite(@TempDir Path tempDir) throws Exception {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 2, "some text", 5, vec(0.1, 0.2, 0.3, 0.4), Map.of("tenant", "acme"));

        JsonNode vector = MAPPER.readTree(lastBodyByKey.get("POST /vectors/upsert")).path("vectors").get(0);
        assertEquals("doc1:2", vector.path("id").asText());
        assertEquals(4, vector.path("values").size());
        assertEquals("doc1", vector.path("metadata").path("document_id").asText());
        assertEquals("acme", vector.path("metadata").path("tenant").asText());
        backend.close();
    }

    @Test
    void searchDenseReturnsChunksWithTextFromSqlite(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);
        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "real chunk text", 5, vec(1, 0, 0, 0), Map.of());

        responders.put("POST /query", body -> "{\"matches\":[{\"id\":\"doc1:0\",\"score\":0.9}]}");

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0), 5, null);

        assertEquals(1, results.size());
        assertEquals("real chunk text", results.get(0).text());
        assertEquals("doc1:0", results.get(0).chunkId());
        assertEquals("test.txt", results.get(0).documentName());
        assertEquals(0.95, results.get(0).similarityScore(), 0.0001); // (0.9 + 1) / 2
        backend.close();
    }

    @Test
    void searchDenseNormalizesCosineSimilarityToUnitRange(@TempDir Path tempDir) throws SQLException {
        // Pinecone's cosine metric returns raw cosine similarity in [-1, 1]
        // (per Pinecone's own explainer); normalized to [0, 1] to match the
        // other backends. Not verified against a live index.
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);
        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "identical vector", 3, vec(1, 0, 0, 0), Map.of());
        backend.insertChunk("doc1", "test.txt", 1, "orthogonal vector", 3, vec(0, 1, 0, 0), Map.of());
        backend.insertChunk("doc1", "test.txt", 2, "opposite vector", 3, vec(-1, 0, 0, 0), Map.of());

        responders.put("POST /query", body -> "{\"matches\":["
                + "{\"id\":\"doc1:0\",\"score\":1.0},"
                + "{\"id\":\"doc1:1\",\"score\":0.0},"
                + "{\"id\":\"doc1:2\",\"score\":-1.0}]}");

        List<SearchResult> results = backend.searchDense(vec(1, 0, 0, 0), 5, null);

        Map<String, Double> scoreByText = new HashMap<>();
        for (SearchResult r : results) scoreByText.put(r.text(), r.similarityScore());

        assertEquals(1.0, scoreByText.get("identical vector"), 0.001);
        assertEquals(0.5, scoreByText.get("orthogonal vector"), 0.001);
        assertEquals(0.0, scoreByText.get("opposite vector"), 0.001);
        backend.close();
    }

    @Test
    void searchDenseSkipsOrphanedVectors(@TempDir Path tempDir) throws SQLException {
        responders.put("POST /query", body -> "{\"matches\":[{\"id\":\"orphaned-not-in-sqlite\",\"score\":0.9}]}");
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        assertTrue(backend.searchDense(vec(0.1, 0.2, 0.3, 0.4), 5, null).isEmpty());
        backend.close();
    }

    @Test
    void searchDenseSendsNativeMetadataFilter(@TempDir Path tempDir) throws Exception {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        backend.searchDense(vec(1, 0, 0, 0), 3, Map.of("tenant", "acme"));

        JsonNode query = MAPPER.readTree(lastBodyByKey.get("POST /query"));
        assertEquals(3, query.path("topK").asInt());
        assertEquals("acme", query.path("filter").path("tenant").path("$eq").asText());
        backend.close();
    }

    @Test
    void dimensionMismatchGuardReturnsEmptyWithoutCallingPinecone(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        assertTrue(backend.searchDense(vec(1, 0), 5, null).isEmpty());
        assertNull(lastBodyByKey.get("POST /query"));
        backend.close();
    }

    @Test
    void searchBeforeInitSchemaReturnsEmpty(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        assertTrue(backend.searchDense(vec(1, 0, 0, 0), 5, null).isEmpty());
        backend.close();
    }

    @Test
    void insertChunkBeforeInitSchemaFailsWithoutLeavingOrphanRow(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.insertDocument("doc1", "test.txt", Map.of());

        assertThrows(IllegalStateException.class, () ->
                backend.insertChunk("doc1", "test.txt", 0, "text", 3, vec(1, 0, 0, 0), Map.of()));
        assertEquals(0, backend.listDocuments(10, 0).get(0).chunkCount());
        backend.close();
    }

    @Test
    void apiErrorSurfacesAsSqlException(@TempDir Path tempDir) throws SQLException {
        statusByKey.put("POST /query", 401);
        responders.put("POST /query", body -> "{\"code\":16,\"message\":\"Unauthorized\"}");
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);

        SQLException e = assertThrows(SQLException.class, () -> backend.searchDense(vec(1, 0, 0, 0), 5, null));
        assertTrue(e.getMessage().contains("401"));
        backend.close();
    }

    @Test
    void deleteDocumentSendsVectorIds(@TempDir Path tempDir) throws Exception {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);
        backend.insertDocument("doc1", "test.txt", Map.of());
        backend.insertChunk("doc1", "test.txt", 0, "text", 3, vec(1, 0, 0, 0), Map.of());

        assertTrue(backend.deleteDocument("doc1"));

        JsonNode body = MAPPER.readTree(lastBodyByKey.get("POST /vectors/delete"));
        assertEquals("doc1:0", body.path("ids").get(0).asText());
        assertEquals(0, backend.listDocuments(10, 0).size());
        backend.close();
    }

    @Test
    void deleteUnknownDocumentReturnsFalse(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);
        assertFalse(backend.deleteDocument("nonexistent-id"));
        assertNull(lastBodyByKey.get("POST /vectors/delete"));
        backend.close();
    }

    @Test
    void supportsSparseIsFalse(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        assertFalse(backend.supportsSparse());
        backend.close();
    }

    @Test
    void getDocumentFilenameReturnsFilenameOrEmpty(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.insertDocument("doc-x", "x.txt", Map.of());

        assertEquals("x.txt", backend.getDocumentFilename("doc-x").orElseThrow());
        assertTrue(backend.getDocumentFilename("nonexistent").isEmpty());
        backend.close();
    }

    @Test
    void listDocumentsAndPagination(@TempDir Path tempDir) throws SQLException {
        PineconeBackend backend = newBackend(tempDir);
        backend.initSchema(DIM);
        backend.insertDocument("doc-a", "a.txt", Map.of());
        backend.insertChunk("doc-a", "a.txt", 0, "text a", 3, vec(1, 0, 0, 0), Map.of());
        backend.insertDocument("doc-b", "b.txt", Map.of());
        backend.insertChunk("doc-b", "b.txt", 0, "text b", 3, vec(0, 1, 0, 0), Map.of());

        assertEquals(2, backend.listDocuments(10, 0).size());
        assertEquals(1, backend.listDocuments(1, 0).size());
        assertEquals(1, backend.listDocuments(1, 1).size());
        assertNotNull(backend.listDocuments(10, 0).get(0).filename());
        backend.close();
    }
}
