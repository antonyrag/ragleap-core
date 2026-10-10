package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import org.junit.jupiter.api.Test;

class GraphIndexTest {
    static final class Scripted implements CypherRunner {
        final List<String> cyphers = new ArrayList<>();
        boolean closed;
        Function<String, RuntimeException> failure = c -> null;
        Function<String, List<Map<String, Object>>> rows = c -> List.of();

        @Override
        public List<Map<String, Object>> run(String cypher, Map<String, Object> params) {
            cyphers.add(cypher);
            RuntimeException f = failure.apply(cypher);
            if (f != null) {
                throw f;
            }
            return rows.apply(cypher);
        }

        @Override
        public void close() {
            closed = true;
        }

        long count(String fragment) {
            return cyphers.stream().filter(c -> c.contains(fragment)).count();
        }
    }

    private static List<Map<String, Object>> chunks(String... texts) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (String t : texts) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("text", t);
            list.add(m);
        }
        return list;
    }

    private static GraphTransientException deadlock() {
        return new GraphTransientException("Neo.TransientError.Transaction.DeadlockDetected: x");
    }

    @Test
    void unreachableServerDegradesGracefully() {
        try (GraphIndex graph = new GraphIndex(new GraphConfig("http://127.0.0.1:1", "x", "x"))) {
            assertFalse(graph.isAvailable());
            assertFalse(graph.healthCheck());
            UpsertSummary s = graph.upsertDocument("d1", "t", chunks("Acme Corp"));
            assertFalse(s.success());
            assertEquals("Neo4j driver not available", s.error());
            assertTrue(graph.findDocumentsByEntities(List.of("Acme Corp")).isEmpty());
            assertTrue(graph.documentEntities("doc-1", null, null).isEmpty());
        }
    }

    @Test
    void failedConnectivityClosesTheRunnerAndMakesTheIndexUnavailable() {
        Scripted r = new Scripted();
        r.failure = c -> new GraphException("refused");
        GraphIndex graph = new GraphIndex(r, null, s -> { });
        assertFalse(graph.isAvailable());
        assertTrue(r.closed);
    }

    @Test
    void constraintsAreCreatedInOrderAndAFailureStopsTheRestButKeepsTheIndexUsable() {
        Scripted r = new Scripted();
        r.failure = c -> c.contains("pairweight_composite_key") ? new GraphException("boom") : null;
        GraphIndex graph = new GraphIndex(r, null, s -> { });
        assertTrue(graph.isAvailable());
        assertEquals(4, r.cyphers.size());
        assertEquals("RETURN 1", r.cyphers.get(0));
        assertTrue(r.cyphers.get(1).contains("document_composite_key"));
        assertTrue(r.cyphers.get(2).contains("entity_composite_key"));
    }

    @Test
    void allSixConstraintsAreCreatedWhenEverythingWorks() {
        Scripted r = new Scripted();
        new GraphIndex(r, null, s -> { });
        assertEquals(7, r.cyphers.size());
        assertTrue(r.cyphers.get(5).contains("co_occurs_with_composite_key"));
        assertTrue(r.cyphers.get(6).contains("relates_as_composite_key"));
    }

    @Test
    void transientErrorsAreRetriedWithBackoff() {
        Scripted r = new Scripted();
        AtomicInteger attempts = new AtomicInteger();
        List<Double> sleeps = new ArrayList<>();
        List<String> audited = new ArrayList<>();
        GraphIndex graph = new GraphIndex(r, (u, n, a, d, c, detail) -> audited.add(a), sleeps::add);
        r.failure = c -> c.contains("MERGE (d:Document") && attempts.incrementAndGet() <= 2 ? deadlock() : null;
        UpsertSummary s = graph.upsertDocument("d1", "t", chunks("Acme Corp and Globex Industries."));
        assertTrue(s.success(), String.valueOf(s));
        assertEquals(2, sleeps.size());
        assertTrue(sleeps.get(0) >= 0.1 && sleeps.get(0) < 0.15, String.valueOf(sleeps));
        assertTrue(sleeps.get(1) >= 0.2 && sleeps.get(1) < 0.25, String.valueOf(sleeps));
        assertEquals(List.of("upsert_document"), audited);
    }

    @Test
    void givesUpAfterThreeTransientErrorsWithoutAuditing() {
        Scripted r = new Scripted();
        List<Double> sleeps = new ArrayList<>();
        List<String> audited = new ArrayList<>();
        GraphIndex graph = new GraphIndex(r, (u, n, a, d, c, detail) -> audited.add(a), sleeps::add);
        r.failure = c -> c.contains("MERGE (d:Document") ? deadlock() : null;
        UpsertSummary s = graph.upsertDocument("d1", "t", chunks("Acme Corp and Globex Industries."));
        assertFalse(s.success());
        assertTrue(s.error().startsWith("Transient Neo4j error persisted after 3 attempts: "), s.error());
        assertTrue(s.error().contains("DeadlockDetected"));
        assertEquals(0, s.entitiesIndexed());
        assertEquals(2, sleeps.size());
        assertTrue(audited.isEmpty());
    }

    @Test
    void otherErrorsAreNotRetried() {
        Scripted r = new Scripted();
        List<Double> sleeps = new ArrayList<>();
        GraphIndex graph = new GraphIndex(r, null, sleeps::add);
        r.failure = c -> c.contains("MERGE (d:Document") ? new GraphException("boom") : null;
        UpsertSummary s = graph.upsertDocument("d1", "t", chunks("Acme Corp and Globex Industries."));
        assertFalse(s.success());
        assertEquals("boom", s.error());
        assertEquals(1, r.count("MERGE (d:Document"));
        assertTrue(sleeps.isEmpty());
    }

    @Test
    void findDocumentsMapsRowsAndAudits() {
        Scripted r = new Scripted();
        List<String> audited = new ArrayList<>();
        GraphIndex graph = new GraphIndex(r, (u, n, a, d, c, detail) -> audited.add(a), s -> { });
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("document_id", "d1");
        row.put("document_name", null);
        row.put("matched_entities", 2L);
        row.put("graph_score", 3.5);
        row.put("matched_entity_names", List.of("Acme Corp"));
        r.rows = c -> c.contains("count(DISTINCT e) AS matched_entities") ? List.of(row) : List.of();
        List<DocumentHit> hits = graph.findDocumentsByEntities(List.of("Acme Corp"), "ns", null, 25);
        assertEquals(List.of(new DocumentHit("d1", "", 2, 3.5, List.of("Acme Corp"))), hits);
        assertEquals(List.of("find_documents_by_entities"), audited);
    }

    @Test
    void findDocumentsSkipsTheQueryWhenNoUsableNames() {
        Scripted r = new Scripted();
        GraphIndex graph = new GraphIndex(r, null, s -> { });
        int before = r.cyphers.size();
        assertTrue(graph.findDocumentsByEntities(List.of("ab", "")).isEmpty());
        assertEquals(before, r.cyphers.size());
    }

    @Test
    void queryErrorsReturnEmptyResults() {
        Scripted r = new Scripted();
        GraphIndex graph = new GraphIndex(r, null, s -> { });
        r.failure = c -> c.contains("AS matched_entities") || c.contains("AS entity_name") ? new GraphException("x") : null;
        assertTrue(graph.findDocumentsByEntities(List.of("Acme Corp")).isEmpty());
        assertTrue(graph.documentEntities("d1", null, null).isEmpty());
    }

    @Test
    void auditFailureNeverBreaksTheOperation() {
        Scripted r = new Scripted();
        GraphIndex graph = new GraphIndex(r, (u, n, a, d, c, detail) -> {
            throw new IllegalStateException("audit down");
        }, s -> { });
        UpsertSummary s = graph.upsertDocument("d1", "t", chunks("Acme Corp and Globex Industries."));
        assertTrue(s.success());
    }
}
