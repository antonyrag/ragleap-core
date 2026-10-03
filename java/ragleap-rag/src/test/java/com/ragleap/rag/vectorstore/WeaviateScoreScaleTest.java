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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Regression test for the Weaviate score scale (found by the cross-backend benchmark, issue 565):
 * scores must be on the same [0, 1] scale as pgvector and Qdrant, where an identical vector scores
 * 1.0, an orthogonal one 0.5 and an opposite one 0.0. Runs against a live Weaviate at localhost:8081
 * and is skipped when none is reachable.
 */
@EnabledIf("weaviateIsReachable")
class WeaviateScoreScaleTest {

    private static final String WEAVIATE_URL = "http://localhost:8081";

    @TempDir
    Path tempDir;

    private WeaviateBackend backend;
    private String collectionName;

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
        collectionName = "ScoreScale" + System.nanoTime();
        backend = new WeaviateBackend(tempDir.resolve("wv").toString(), WEAVIATE_URL, null, collectionName);
        backend.initSchema(4);
    }

    @AfterEach
    void tearDown() throws Exception {
        backend.close();
        HttpClient.newHttpClient().send(
                HttpRequest.newBuilder().uri(URI.create(WEAVIATE_URL + "/v1/schema/" + collectionName)).DELETE().build(),
                HttpResponse.BodyHandlers.discarding());
    }

    private void store(String name, double... v) throws Exception {
        String id = UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)).toString();
        List<Double> embedding = java.util.Arrays.stream(v).boxed().toList();
        backend.insertDocument(id, name, Map.of("k", "v"));
        backend.insertChunk(id, name, 0, "text of " + name, 3, embedding, Map.of("k", "v"));
    }

    @Test
    void scoresAreOnTheZeroToOneScaleForIdenticalOrthogonalAndOppositeVectors() throws Exception {
        store("identical", 1, 0, 0, 0);
        store("diagonal", 1, 1, 0, 0);
        store("orthogonal", 0, 1, 0, 0);
        store("opposite", -1, 0, 0, 0);

        List<SearchResult> results = backend.searchDense(List.of(1.0, 0.0, 0.0, 0.0), 10, Map.of());
        assertEquals(4, results.size());

        Map<String, Double> score = new HashMap<>();
        for (SearchResult r : results) {
            score.put(r.documentName(), r.similarityScore());
            assertTrue(r.similarityScore() >= 0.0 && r.similarityScore() <= 1.0, "score outside [0, 1]: " + r);
        }
        assertEquals(1.0, score.get("identical"), 0.001);
        assertEquals(0.8536, score.get("diagonal"), 0.001); // cosine 0.7071 -> (0.7071 + 1) / 2
        assertEquals(0.5, score.get("orthogonal"), 0.001);
        assertEquals(0.0, score.get("opposite"), 0.001);

        assertEquals("identical", results.get(0).documentName());
        assertEquals("opposite", results.get(3).documentName());
    }
}
