package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.api.io.TempDir;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * Weaviate creates a property only when the first object that has it is stored. Searching a new
 * collection, or filtering on a key no chunk has, must return no results instead of a GraphQL error
 * (found by the failure-mode matrix, issue 565). Needs Weaviate at localhost:8081; skipped otherwise.
 */
@EnabledIf("weaviateIsReachable")
class WeaviateMissingPropertiesTest {

    private static final String WEAVIATE_URL = "http://localhost:8081";
    private static final List<Double> Q = List.of(1.0, 0.0, 0.0, 0.0);

    @TempDir
    Path tempDir;

    private WeaviateBackend backend;
    private String collection;

    static boolean weaviateIsReachable() {
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(WEAVIATE_URL + "/v1/.well-known/ready")).GET().build();
            return client.send(req, HttpResponse.BodyHandlers.discarding()).statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    @BeforeEach
    void setUp() throws Exception {
        collection = "MissingProps" + System.nanoTime();
        backend = new WeaviateBackend(tempDir.resolve("wv").toString(), WEAVIATE_URL, null, collection);
        backend.initSchema(4);
    }

    @AfterEach
    void tearDown() throws Exception {
        backend.close();
        HttpClient.newHttpClient().send(
                HttpRequest.newBuilder().uri(URI.create(WEAVIATE_URL + "/v1/schema/" + collection)).DELETE().build(),
                HttpResponse.BodyHandlers.discarding());
    }

    private void store(String name, Map<String, Object> metadata) throws Exception {
        String id = UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)).toString();
        backend.insertDocument(id, name, metadata);
        backend.insertChunk(id, name, 0, "text of " + name, 3, Q, metadata);
    }

    @Test
    void searchOnACollectionWithNoDataReturnsNoResults() throws Exception {
        assertEquals(0, backend.searchDense(Q, 5, Map.of()).size());
    }

    @Test
    void searchWorksOnceTheFirstChunkIsStored() throws Exception {
        assertEquals(0, backend.searchDense(Q, 5, Map.of()).size());
        store("first", Map.of("k", "v"));
        assertEquals(1, backend.searchDense(Q, 5, Map.of()).size());
    }

    @Test
    void filterOnAKeyNoChunkHasReturnsNoResults() throws Exception {
        store("first", Map.of("k", "v"));
        assertEquals(0, backend.searchDense(Q, 5, Map.of("nokey", "x")).size());
        assertEquals(1, backend.searchDense(Q, 5, Map.of("k", "v")).size());
    }

    @Test
    void aMissingKeyIsNotRememberedAsMissingOnceAChunkWithItIsStored() throws Exception {
        assertEquals(0, backend.searchDense(Q, 5, Map.of("late", "x")).size());
        store("later", Map.of("late", "x"));
        assertEquals(1, backend.searchDense(Q, 5, Map.of("late", "x")).size());
    }
}
