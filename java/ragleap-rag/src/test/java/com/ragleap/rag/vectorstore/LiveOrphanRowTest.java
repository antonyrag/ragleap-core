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
 * When the server rejects a chunk write, the local row must not be left behind, so the same chunk can be
 * retried (found by the failure-mode matrix, issue 565). Each test skips itself when its service is not
 * reachable. Qdrant trigger: the collection has been deleted (HTTP 404). Weaviate trigger: a metadata
 * value of the wrong type for an existing text property (HTTP 422).
 */
class LiveOrphanRowTest {

    private static final String QDRANT_URL = "http://localhost:6333";
    private static final String WEAVIATE_URL = "http://localhost:8081";
    private static final List<Double> V = List.of(1.0, 0.0, 0.0, 0.0);

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

    private static void send(HttpRequest.Builder b) throws Exception {
        HttpClient.newHttpClient().send(b.build(), HttpResponse.BodyHandlers.discarding());
    }

    private static String uid(String name) {
        return UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)).toString();
    }

    @Test
    @EnabledIf("qdrantIsReachable")
    void qdrantRemovesTheLocalRowWhenTheServerWriteFailsSoTheChunkCanBeRetried() throws Exception {
        String collection = "orphan_" + System.nanoTime();
        QdrantBackend b = new QdrantBackend(tempDir.resolve("qd").toString(), QDRANT_URL, null, collection);
        try {
            b.initSchema(4);
            String id = uid("orphan-q");
            b.insertDocument(id, "o.txt", Map.of("k", "v"));

            send(HttpRequest.newBuilder().uri(URI.create(QDRANT_URL + "/collections/" + collection)).DELETE());
            assertThrows(SQLException.class, () -> b.insertChunk(id, "o.txt", 0, "t", 1, V, Map.of("k", "v")));

            send(HttpRequest.newBuilder().uri(URI.create(QDRANT_URL + "/collections/" + collection))
                    .header("Content-Type", "application/json")
                    .PUT(HttpRequest.BodyPublishers.ofString("{\"vectors\":{\"size\":4,\"distance\":\"Cosine\"}}")));
            b.insertChunk(id, "o.txt", 0, "t", 1, V, Map.of("k", "v"));

            assertEquals(1, b.searchDense(V, 5, Map.of()).size());
            assertEquals(1L, b.listDocuments(10, 0).get(0).chunkCount());
        } finally {
            b.close();
            send(HttpRequest.newBuilder().uri(URI.create(QDRANT_URL + "/collections/" + collection)).DELETE());
        }
    }

    @Test
    @EnabledIf("weaviateIsReachable")
    void weaviateRemovesTheLocalRowWhenTheServerWriteFailsSoTheChunkCanBeRetried() throws Exception {
        String collection = "Orphan" + System.nanoTime();
        WeaviateBackend b = new WeaviateBackend(tempDir.resolve("wv").toString(), WEAVIATE_URL, null, collection);
        try {
            b.initSchema(4);
            String id = uid("orphan-w");
            b.insertDocument(id, "o.txt", Map.of("k", "v"));
            b.insertChunk(id, "o.txt", 0, "first", 1, V, Map.of("k", "v")); // creates property k as text

            assertThrows(SQLException.class, () -> b.insertChunk(id, "o.txt", 1, "second", 1, V, Map.of("k", 5)));

            b.insertChunk(id, "o.txt", 1, "second", 1, V, Map.of("k", "w"));

            assertEquals(2, b.searchDense(V, 5, Map.of()).size());
            assertEquals(2L, b.listDocuments(10, 0).get(0).chunkCount());
        } finally {
            b.close();
            send(HttpRequest.newBuilder().uri(URI.create(WEAVIATE_URL + "/v1/schema/" + collection)).DELETE());
        }
    }
}
