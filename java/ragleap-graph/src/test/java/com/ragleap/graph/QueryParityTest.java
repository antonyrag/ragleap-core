package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares Cypher, parameters, return values and audit events with the real Python code, per method call. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class QueryParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, List<Map<String, Object>>>> ROWS = new TypeReference<>() { };

    static final class Recorder implements CypherRunner {
        final List<UpsertParityTest.Call> calls = new ArrayList<>();
        final Map<String, List<Map<String, Object>>> rows;

        Recorder(Map<String, List<Map<String, Object>>> rows) {
            this.rows = rows;
        }

        @Override
        public List<Map<String, Object>> run(String cypher, Map<String, Object> params) {
            calls.add(new UpsertParityTest.Call(UpsertParityTest.strip(cypher),
                    UpsertParityTest.canon(MAPPER.valueToTree(params))));
            String key = cypher.contains("PairWeight") ? "pair" : cypher.contains("RelationWeight") ? "relation" : "default";
            return new ArrayList<>(rows.getOrDefault(key, List.of()));
        }
    }

    private static String text(JsonNode n) {
        return n == null || n.isNull() ? null : n.asText();
    }

    private static List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        for (JsonNode e : n) {
            out.add(e.asText());
        }
        return out;
    }

    private static Map<String, Object> m(Object... kv) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            map.put((String) kv[i], kv[i + 1]);
        }
        return map;
    }

    private static Object invoke(GraphIndex g, String method, JsonNode a) {
        List<Object> out = new ArrayList<>();
        switch (method) {
            case "search_related_entities":
                for (RelatedEntity r : g.searchRelatedEntities(strings(a.get("entity_names")), text(a.get("namespace")),
                        text(a.get("user_id")), a.get("max_depth").asInt(), a.get("limit").asInt())) {
                    out.add(m("entity_id", r.entityId(), "entity_name", r.entityName(),
                            "relationship", r.relationship(), "depth", r.depth()));
                }
                return out;
            case "find_relations":
                for (RelationHit r : g.findRelations(text(a.get("entity_name")), text(a.get("relation_type")),
                        text(a.get("namespace")), text(a.get("user_id")), a.get("limit").asInt(),
                        text(a.get("direction")))) {
                    out.add(m("subject", r.subject(), "relation_type", r.relationType(), "object", r.object(),
                            "weight", r.weight()));
                }
                return out;
            case "find_lineage":
                for (LineageEntry e : g.findLineage(text(a.get("entity_a")), text(a.get("entity_b")),
                        text(a.get("relation_type")), text(a.get("namespace")), text(a.get("user_id")),
                        a.get("limit").asInt())) {
                    if ("RELATES_AS".equals(e.relationType())) {
                        out.add(m("document_id", e.documentId(), "relation_type", e.relationType(),
                                "relation_name", e.relationName(), "weight", e.weight()));
                    } else {
                        out.add(m("document_id", e.documentId(), "relation_type", e.relationType(),
                                "weight", e.weight()));
                    }
                }
                return out;
            case "find_entities_by_type":
                for (TypedEntity e : g.findEntitiesByType(text(a.get("entity_type")), text(a.get("namespace")),
                        text(a.get("user_id")), a.get("limit").asInt())) {
                    out.add(m("entity_id", e.entityId(), "entity_name", e.entityName(), "entity_type", e.entityType()));
                }
                return out;
            case "find_documents_by_entities":
                for (DocumentHit h : g.findDocumentsByEntities(strings(a.get("entity_names")), text(a.get("namespace")),
                        text(a.get("user_id")), a.get("limit").asInt())) {
                    out.add(m("document_id", h.documentId(), "document_name", h.documentName(),
                            "matched_entities", h.matchedEntities(), "graph_score", h.graphScore(),
                            "matched_entity_names", h.matchedEntityNames()));
                }
                return out;
            case "document_entities":
                for (EntityRef e : g.documentEntities(text(a.get("document_id")), text(a.get("namespace")),
                        text(a.get("user_id")))) {
                    out.add(m("entity_id", e.entityId(), "entity_name", e.entityName()));
                }
                return out;
            default:
                throw new IllegalStateException("unknown method " + method);
        }
    }

    private static String abbreviate(String s) {
        return s.length() > 300 ? s.substring(0, 300) + "..." : s;
    }

    @Test
    void queryMethodsMatchPython() throws IOException {
        Path file = Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR")).resolve("query_cases.json");
        JsonNode cases = MAPPER.readTree(file.toFile());
        List<String> bad = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            Recorder rec = new Recorder(MAPPER.convertValue(c.get("rows"), ROWS));
            List<String> audits = new ArrayList<>();
            AuditSink sink = (u, n, act, doc, cnt, detail) -> {
                ObjectNode o = MAPPER.createObjectNode();
                o.put("user_id", u);
                o.put("namespace", n);
                o.put("action", act);
                if (doc == null) {
                    o.putNull("document_id");
                } else {
                    o.put("document_id", doc);
                }
                if (cnt == null) {
                    o.putNull("entity_count");
                } else {
                    o.put("entity_count", cnt.intValue());
                }
                o.set("detail", MAPPER.valueToTree(detail));
                audits.add(UpsertParityTest.canon(o));
            };
            GraphIndex graph = c.get("no_driver").asBoolean()
                    ? new GraphIndex((CypherRunner) null, sink, s -> { })
                    : new GraphIndex(rec, sink, s -> { });
            rec.calls.clear();
            Object result = null;
            String raised = null;
            try {
                result = invoke(graph, c.get("method").asText(), c.get("args"));
            } catch (IllegalArgumentException e) {
                raised = e.getMessage();
            }
            JsonNode exp = c.get("expected");
            String expRaises = text(exp.get("raises"));
            if (expRaises != null || raised != null) {
                if (expRaises == null || !expRaises.equals(raised)) {
                    bad.add(name + ": raises java=" + raised + " python=" + expRaises);
                    continue;
                }
            } else {
                String got = UpsertParityTest.canon(MAPPER.valueToTree(result));
                String want = UpsertParityTest.canon(exp.get("result"));
                if (!got.equals(want)) {
                    bad.add(name + ": result differs\n  java:   " + abbreviate(got) + "\n  python: " + abbreviate(want));
                    continue;
                }
            }
            List<UpsertParityTest.Call> expected = new ArrayList<>();
            for (JsonNode call : c.get("calls")) {
                expected.add(new UpsertParityTest.Call(call.get("cypher").asText(),
                        UpsertParityTest.canon(call.get("params"))));
            }
            if (!expected.equals(rec.calls)) {
                String detail = "";
                for (int i = 0; i < Math.max(expected.size(), rec.calls.size()); i++) {
                    if (i >= expected.size() || i >= rec.calls.size() || !expected.get(i).equals(rec.calls.get(i))) {
                        detail = " first difference at statement " + i
                                + "\n  java:   " + (i < rec.calls.size() ? abbreviate(rec.calls.get(i).toString()) : "none")
                                + "\n  python: " + (i < expected.size() ? abbreviate(expected.get(i).toString()) : "none");
                        break;
                    }
                }
                bad.add(name + ": statements differ (java " + rec.calls.size() + ", python " + expected.size() + ")" + detail);
                continue;
            }
            List<String> expAudits = new ArrayList<>();
            for (JsonNode ev : c.get("audit")) {
                expAudits.add(UpsertParityTest.canon(ev));
            }
            if (!expAudits.equals(audits)) {
                bad.add(name + ": audit events differ\n  java:   " + abbreviate(audits.toString())
                        + "\n  python: " + abbreviate(expAudits.toString()));
            }
        }
        assertTrue(bad.isEmpty(), cases.size() + " scenarios, " + bad.size() + " problems:\n" + String.join("\n", bad));
    }
}
