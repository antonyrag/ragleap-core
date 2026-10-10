package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Runs against a real Neo4j test server. Every test uses its own unique namespace and removes its data. */
@EnabledIfEnvironmentVariable(named = "NEO4J_HTTP_URL", matches = ".+")
class LiveNeo4jTest {
    private static GraphConfig config() {
        return new GraphConfig(System.getenv("NEO4J_HTTP_URL"),
                System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
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

    private static void cleanup(CypherRunner r, String ns) {
        r.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
    }

    private static long count(CypherRunner r, String cypher, Map<String, Object> params) {
        return ((Number) r.run(cypher, params).get(0).get("cnt")).longValue();
    }

    private static Object weight(CypherRunner r, String ns, String a, String b) {
        List<Map<String, Object>> rows = r.run(
                "MATCH (:Entity {name: $a, namespace: $ns})-[c:CO_OCCURS_WITH]-(:Entity {name: $b, namespace: $ns}) "
                        + "RETURN c.weight AS w", Map.of("a", a, "b", b, "ns", ns));
        assertEquals(1, rows.size());
        return rows.get(0).get("w");
    }

    @Test
    void roundTrip() {
        String ns = "ragleap_graph_java_" + UUID.randomUUID();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                assertTrue(graph.healthCheck());
                UpsertSummary s = graph.upsertDocument("java-live-doc-1", "Java Live Test Document",
                        chunks("Acme Corp announced a partnership with Globex Industries."), ns);
                assertTrue(s.success(), String.valueOf(s));
                assertTrue(s.entitiesIndexed() > 0);
                List<DocumentHit> docs = graph.findDocumentsByEntities(List.of("Acme Corp"), ns, null, 25);
                assertEquals(1, docs.size());
                assertEquals("java-live-doc-1", docs.get(0).documentId());
                assertEquals("Java Live Test Document", docs.get(0).documentName());
                Set<String> names = new HashSet<>();
                for (EntityRef e : graph.documentEntities("java-live-doc-1", ns, null)) {
                    names.add(e.entityName());
                }
                assertTrue(names.contains("Acme Corp"), String.valueOf(names));
                assertTrue(names.contains("Globex Industries"), String.valueOf(names));
            } finally {
                cleanup(direct, ns);
            }
        }
    }

    @Test
    void containsEdgesAreIdempotentAndStaleOnesAreRemoved() {
        String ns = "ragleap_graph_java_" + UUID.randomUUID();
        String q = "MATCH (d:Document {id: $id, namespace: $ns})-[r:CONTAINS]->(e:Entity) RETURN e.name AS n, r.weight AS w";
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                graph.upsertDocument("idem-doc", "T", chunks("Acme Corp and Globex Industries."), ns);
                graph.upsertDocument("idem-doc", "T", chunks("Acme Corp and Globex Industries."), ns);
                List<Map<String, Object>> rows = direct.run(q, Map.of("id", "idem-doc", "ns", ns));
                assertEquals(2, rows.size());
                for (Map<String, Object> row : rows) {
                    assertInstanceOf(Double.class, row.get("w"));
                    assertEquals(1.0, (Double) row.get("w"));
                }
                graph.upsertDocument("idem-doc", "T", chunks("Acme Corp only here."), ns);
                rows = direct.run(q, Map.of("id", "idem-doc", "ns", ns));
                assertEquals(1, rows.size());
                assertEquals("acme corp", rows.get(0).get("n"));
            } finally {
                cleanup(direct, ns);
            }
        }
    }

    @Test
    void coOccursWeightsTrackPerDocumentContributions() {
        String ns = "ragleap_graph_java_" + UUID.randomUUID();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                graph.upsertDocument("cooccur-doc-a", "Test", chunks("Acme Corp and Globex Corp are rivals."), ns);
                graph.upsertDocument("cooccur-doc-a", "Test", chunks("Acme Corp and Globex Corp are rivals."), ns);
                Object w = weight(direct, ns, "acme corp", "globex corp");
                assertInstanceOf(Double.class, w);
                assertEquals(1.0, (Double) w);
                graph.upsertDocument("cooccur-doc-b", "Test2", chunks("Acme Corp and Globex Corp compete fiercely."), ns);
                assertEquals(2.0, (Double) weight(direct, ns, "acme corp", "globex corp"));
                graph.upsertDocument("cooccur-doc-b", "Test2", chunks("Totally unrelated content now, no companies."), ns);
                assertEquals(1.0, (Double) weight(direct, ns, "acme corp", "globex corp"));
            } finally {
                cleanup(direct, ns);
            }
        }
    }

    @Test
    void concurrentUpsertsOfTheSameDocumentCreateNoDuplicates() throws Exception {
        String ns = "ragleap_graph_java_" + UUID.randomUUID();
        String docId = "java-concurrency-doc-" + UUID.randomUUID();
        String userId = "java-concurrency-user-" + UUID.randomUUID();
        List<Map<String, Object>> chunks = chunks("Alice works at Acme Corporation as a senior engineer.",
                "Acme Corporation is headquartered in Springfield.");
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                int threads = 8;
                ExecutorService pool = Executors.newFixedThreadPool(threads);
                CountDownLatch start = new CountDownLatch(1);
                List<Future<UpsertSummary>> futures = new ArrayList<>();
                for (int i = 0; i < threads; i++) {
                    Callable<UpsertSummary> task = () -> {
                        start.await();
                        return graph.upsertDocument(docId, "Concurrency Test", chunks, ns, userId, 80, 150, null);
                    };
                    futures.add(pool.submit(task));
                }
                start.countDown();
                int successes = 0;
                for (Future<UpsertSummary> f : futures) {
                    UpsertSummary s = f.get(120, TimeUnit.SECONDS);
                    assertTrue(s.success() || (s.error() != null && s.error().contains("DeadlockDetected")),
                            "unexpected failure: " + s);
                    if (s.success()) {
                        successes++;
                    }
                }
                pool.shutdown();
                assertTrue(successes > 0, "no upsert succeeded");
                Map<String, Object> p = Map.of("id", docId, "u", userId, "ns", ns);
                assertEquals(1, count(direct,
                        "MATCH (d:Document {id: $id, user_id: $u, namespace: $ns}) RETURN count(d) AS cnt", p));
                assertEquals(1, count(direct,
                        "MATCH (e:Entity {name: 'acme corporation', user_id: $u, namespace: $ns}) RETURN count(e) AS cnt", p));
                List<Map<String, Object>> pairs = direct.run(
                        "MATCH (pw:PairWeight {document_id: $id, user_id: $u, namespace: $ns}) "
                                + "RETURN pw.entity_a AS a, pw.entity_b AS b", p);
                Set<String> distinct = new HashSet<>();
                for (Map<String, Object> row : pairs) {
                    distinct.add(row.get("a") + "|" + row.get("b"));
                }
                assertEquals(distinct.size(), pairs.size(), "duplicate PairWeight nodes: " + pairs);
            } finally {
                cleanup(direct, ns);
            }
        }
    }
}
