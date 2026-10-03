package com.ragleap.rag.vectorstore;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Regression test for the FAISS score scale (found by the cross-backend benchmark, issue 565):
 * scores sit on the same [0, 1] scale as pgvector, Qdrant and Weaviate, where an identical vector
 * scores 1.0, an orthogonal one 0.5 and an opposite one 0.0. Needs no external services.
 */
class FaissScoreScaleTest {

    private static void store(FaissBackend backend, String name, double... v) throws Exception {
        String id = UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)).toString();
        List<Double> embedding = Arrays.stream(v).boxed().toList();
        backend.insertDocument(id, name, Map.of("k", "v"));
        backend.insertChunk(id, name, 0, "text of " + name, 3, embedding, Map.of("k", "v"));
    }

    @Test
    void scoresAreOnTheZeroToOneScaleForIdenticalOrthogonalAndOppositeVectors() throws Exception {
        FaissBackend backend = new FaissBackend();
        backend.initSchema(4);
        store(backend, "identical", 1, 0, 0, 0);
        store(backend, "diagonal", 1, 1, 0, 0);
        store(backend, "orthogonal", 0, 1, 0, 0);
        store(backend, "opposite", -1, 0, 0, 0);

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
