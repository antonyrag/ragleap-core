package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares the Cypher statements and parameters Java sends with those the real Python code sends. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class UpsertParityTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    record Call(String cypher, String params) {
    }

    static String strip(String cypher) {
        return cypher.replaceAll("\\s+", "");
    }

    static String canon(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return "null";
        }
        if (n.isObject()) {
            List<String> keys = new ArrayList<>();
            n.fieldNames().forEachRemaining(keys::add);
            Collections.sort(keys);
            StringBuilder sb = new StringBuilder("{");
            for (String k : keys) {
                sb.append(k.length()).append(':').append(k).append('=').append(canon(n.get(k))).append(',');
            }
            return sb.append('}').toString();
        }
        if (n.isArray()) {
            StringBuilder sb = new StringBuilder("[");
            for (JsonNode e : n) {
                sb.append(canon(e)).append(',');
            }
            return sb.append(']').toString();
        }
        if (n.isIntegralNumber()) {
            return "i" + n.bigIntegerValue();
        }
        if (n.isFloatingPointNumber()) {
            return "f" + n.doubleValue();
        }
        if (n.isBoolean()) {
            return "b" + n.booleanValue();
        }
        return "s" + n.asText().length() + ":" + n.asText();
    }

    static final class Recorder implements CypherRunner {
        final List<Call> calls = new ArrayList<>();
        final JsonNode oldPairs;
        final JsonNode oldRelations;

        Recorder(JsonNode oldPairs, JsonNode oldRelations) {
            this.oldPairs = oldPairs;
            this.oldRelations = oldRelations;
        }

        @Override
        public List<Map<String, Object>> run(String cypher, Map<String, Object> params) {
            calls.add(new Call(strip(cypher), canon(MAPPER.valueToTree(params))));
            List<Map<String, Object>> rows = new ArrayList<>();
            if (cypher.contains("RETURN pw.entity_a AS a")) {
                for (JsonNode p : oldPairs) {
                    rows.add(Map.of("a", p.get(0).asText(), "b", p.get(1).asText()));
                }
            } else if (cypher.contains("RETURN rw.subject AS subject")) {
                for (JsonNode p : oldRelations) {
                    rows.add(Map.of("subject", p.get(0).asText(), "relation_type", p.get(1).asText(),
                            "object", p.get(2).asText()));
                }
            }
            return rows;
        }
    }

    /** Python iterates a set when recomputing edges, so statements in each FOREACH block come in arbitrary order. */
    static List<Call> normalize(List<Call> in) {
        List<Call> out = new ArrayList<>();
        List<Call> block = new ArrayList<>();
        for (Call c : in) {
            if (c.cypher().contains("FOREACH")) {
                block.add(c);
            } else {
                flush(out, block);
                out.add(c);
            }
        }
        flush(out, block);
        return out;
    }

    private static void flush(List<Call> out, List<Call> block) {
        block.sort((x, y) -> (x.cypher() + x.params()).compareTo(y.cypher() + y.params()));
        out.addAll(block);
        block.clear();
    }

    private static String text(JsonNode n) {
        return n.isNull() ? null : n.asText();
    }

    @Test
    void upsertStatementsMatchPython() throws IOException {
        Path file = Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR")).resolve("upsert_cases.json");
        JsonNode cases = MAPPER.readTree(file.toFile());
        List<String> bad = new ArrayList<>();
        for (JsonNode c : cases) {
            String name = c.get("name").asText();
            Recorder rec = new Recorder(c.get("old_pairs"), c.get("old_relations"));
            GraphIndex graph = new GraphIndex(rec, AuditSink.NOOP, s -> { });
            rec.calls.clear();
            JsonNode a = c.get("args");
            List<Map<String, Object>> chunks = MAPPER.convertValue(a.get("chunks"),
                    new TypeReference<List<Map<String, Object>>>() { });
            List<String> terms = a.get("domain_terms").isNull() ? null
                    : MAPPER.convertValue(a.get("domain_terms"), new TypeReference<List<String>>() { });
            UpsertSummary s = graph.upsertDocument(a.get("document_id").asText(), text(a.get("title")), chunks,
                    text(a.get("namespace")), text(a.get("user_id")), a.get("max_entities").asInt(),
                    a.get("max_pairs").asInt(), terms);
            JsonNode es = c.get("summary");
            if (s.success() != es.get("success").asBoolean()
                    || s.entitiesIndexed() != es.get("entities_indexed").asInt()
                    || s.relationshipsIndexed() != es.get("relationships_indexed").asInt()
                    || s.relationsIndexed() != es.get("relations_indexed").asInt()
                    || s.error() != null) {
                bad.add(name + ": summary differs, java=" + s + " python=" + es);
            }
            List<Call> expected = new ArrayList<>();
            for (JsonNode call : c.get("calls")) {
                expected.add(new Call(call.get("cypher").asText(), canon(call.get("params"))));
            }
            List<Call> actual = normalize(rec.calls);
            expected = normalize(expected);
            if (actual.size() != expected.size()) {
                bad.add(name + ": " + actual.size() + " statements, python sent " + expected.size());
                continue;
            }
            for (int i = 0; i < actual.size(); i++) {
                if (!actual.get(i).equals(expected.get(i))) {
                    bad.add(name + ": statement " + i + " differs\n  java:   " + abbreviate(actual.get(i))
                            + "\n  python: " + abbreviate(expected.get(i)));
                    break;
                }
            }
        }
        assertTrue(bad.isEmpty(), cases.size() + " scenarios, " + bad.size() + " problems:\n" + String.join("\n", bad));
        assertEquals(14, cases.size());
    }

    private static String abbreviate(Call c) {
        String s = c.cypher().substring(0, Math.min(60, c.cypher().length())) + " | " + c.params();
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }
}
