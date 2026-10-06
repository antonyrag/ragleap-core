package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.api.io.TempDir;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.SQLException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * A wrong-length embedding must be rejected before the local sidecar row or the server is touched, so the
 * same chunk can be retried (found by the failure-mode matrix, issue 565). Needs Qdrant at localhost:6333
 * and/or Weaviate at localhost:8081; each test skips itself when its service is not reachable.
 */
class LiveDimensionValidationTest {

    private static final String QDRANT_URL = "http://localhost:6333";
    private static final String WEAVIATE_URL = "http://localhost:8081";

    @TempDir
    Path tempDir;

    private static boolean reachable(String url) {
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(url)).GET().build();
            return client.send(req, HttpResponse.BodyHandlers.discarding()).statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    static boolean qdrantIsReachable() {
        return reachable(QDRANT_URL + "/");
    }

    static boolean weaviateIsReachable() {
        return reachable(WEAVIATE_URL + "/v1/.well-known/ready");
    }

    private static void httpDelete(String url) throws Exception {
        HttpClient.newHttpClient().send(HttpRequest.newBuilder().uri(URI.create(url)).DELETE().build(),
                HttpResponse.BodyHandlers.discarding());
    }

    private static void check(VectorBackend b) throws Exception {
        b.initSchema(4);
        String id = UUID.nameUUIDFromBytes("dimval".getBytes(StandardCharsets.UTF_8)).toString();
        b.insertDocument(id, "d.txt", Map.of("k", "v"));
        SQLException ex = assertThrows(SQLException.class,
                () -> b.insertChunk(id, "d.txt", 0, "t", 1, List.of(1.0, 0.0, 0.0), Map.of("k", "v")));
        assertEquals("expected 4 dimensions, not 3", ex.getMessage());

        b.insertChunk(id, "d.txt", 0, "t", 1, List.of(1.0, 0.0, 0.0, 0.0), Map.of("k", "v"));
        assertEquals(1, b.searchDense(List.of(1.0, 0.0, 0.0, 0.0), 5, Map.of()).size());
        assertEquals(1L, b.listDocuments(10, 0).get(0).chunkCount());
    }

    @Test
    @EnabledIf("qdrantIsReachable")
    void qdrantRejectsAWrongDimensionBeforeWritingAndAllowsARetry() throws Exception {
        String collection = "dimval_" + System.nanoTime();
        QdrantBackend b = new QdrantBackend(tempDir.resolve("qd").toString(), QDRANT_URL, null, collection);
        try {
            check(b);
        } finally {
            b.close();
            httpDelete(QDRANT_URL + "/collections/" + collection);
        }
    }

    @Test
    @EnabledIf("weaviateIsReachable")
    void weaviateRejectsAWrongDimensionBeforeWritingAndAllowsARetry() throws Exception {
        String collection = "DimVal" + System.nanoTime();
        WeaviateBackend b = new WeaviateBackend(tempDir.resolve("wv").toString(), WEAVIATE_URL, null, collection);
        try {
            check(b);
        } finally {
            b.close();
            httpDelete(WEAVIATE_URL + "/v1/schema/" + collection);
        }
    }
}
