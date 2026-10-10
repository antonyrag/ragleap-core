package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Runs against a real Neo4j test server, in a unique namespace that is removed afterwards. */
@EnabledIfEnvironmentVariable(named = "NEO4J_HTTP_URL", matches = ".+")
class LiveQueryTest {
    private static GraphConfig config() {
        return new GraphConfig(System.getenv("NEO4J_HTTP_URL"),
                System.getenv().getOrDefault("NEO4J_USER", "neo4j"),
                System.getenv().getOrDefault("NEO4J_PASSWORD", ""));
    }

    private static List<Map<String, Object>> chunks(String text) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("text", text);
        List<Map<String, Object>> list = new ArrayList<>();
        list.add(m);
        return list;
    }

    @Test
    void queryMethodsOnASeededGraph() {
        String ns = "ragleap_graph_java_" + UUID.randomUUID();
        try (QueryApiRunner direct = new QueryApiRunner(config()); GraphIndex graph = new GraphIndex(config())) {
            try {
                graph.upsertDocument("cooccur-doc-a", "Test", chunks("Acme Corp and Globex Corp are rivals."), ns);
                graph.upsertDocument("cooccur-doc-b", "Test2", chunks("Acme Corp and Globex Corp compete fiercely."), ns);

                List<RelatedEntity> related = graph.searchRelatedEntities(List.of("Acme Corp"), ns, null, 2, 10);
                assertTrue(related.stream().anyMatch(r -> "Globex Corp".equals(r.entityName()) && r.depth() == 1
                        && "CO_OCCURS_WITH".equals(r.relationship())), related.toString());

                List<LineageEntry> lineage = graph.findLineage("Acme Corp", "Globex Corp", null, ns, null, 25);
                assertEquals(2, lineage.size(), lineage.toString());
                Set<String> docs = new HashSet<>();
                for (LineageEntry e : lineage) {
                    assertEquals("CO_OCCURS_WITH", e.relationType());
                    assertEquals(1.0, e.weight().doubleValue());
                    docs.add(e.documentId());
                }
                assertEquals(Set.of("cooccur-doc-a", "cooccur-doc-b"), docs);

                assertEquals(2, graph.findEntitiesByType("unknown", ns, null, 25).size());
                assertEquals(0, graph.findEntitiesByType("person", ns, null, 25).size());

                direct.run("MATCH (a:Entity {name: 'acme corp', namespace: $ns}), (b:Entity {name: 'globex corp', namespace: $ns}) "
                        + "MERGE (a)-[r:RELATES_AS {composite_key: $ck}]->(b) "
                        + "SET r.relation_type = 'PARTNERED_WITH', r.weight = 2.0, r.namespace = $ns, r.user_id = ''",
                        Map.of("ns", ns, "ck", CompositeKey.of(ns, "", "acme corp", "PARTNERED_WITH", "globex corp")));

                List<RelationHit> out = graph.findRelations("Acme Corp", null, ns, null, 25, "outgoing");
                assertEquals(1, out.size(), out.toString());
                assertEquals(new RelationHit("Acme Corp", "PARTNERED_WITH", "Globex Corp", 2.0), out.get(0));
                assertEquals(1, graph.findRelations("Globex Corp", null, ns, null, 25, "incoming").size());
                assertEquals(0, graph.findRelations("Globex Corp", null, ns, null, 25, "outgoing").size());
                assertEquals(1, graph.findRelations("Globex Corp", null, ns, null, 25, "both").size());
                assertEquals(0, graph.findRelations("Acme Corp", "OTHER", ns, null, 25, "outgoing").size());
            } finally {
                direct.run("MATCH (n) WHERE n.namespace = $ns DETACH DELETE n", Map.of("ns", ns));
            }
        }
    }
}
