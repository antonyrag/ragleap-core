package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares Java output with fixtures generated from the pinned Python source. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class ParityTest {
    private static JsonNode cases() throws IOException {
        Path dir = Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"));
        return new ObjectMapper().readTree(dir.resolve("cases.json").toFile());
    }

    private static String show(Object o) {
        if (o == null) {
            return "null";
        }
        String s = o.toString();
        StringBuilder sb = new StringBuilder("'");
        s.codePoints().forEach(cp -> {
            if (cp < 0x20 || cp > 0x7E) {
                sb.append("\\u{").append(Integer.toHexString(cp)).append('}');
            } else {
                sb.append((char) cp);
            }
        });
        return sb.append("'").toString();
    }

    private static void check(String what, int total, List<String> bad) {
        assertTrue(bad.isEmpty(), () -> what + ": " + total + " cases, " + bad.size() + " mismatches:\n"
                + String.join("\n", bad.subList(0, Math.min(bad.size(), 30))));
    }

    @Test
    void normalize() throws IOException {
        JsonNode arr = cases().get("normalize");
        List<String> bad = new ArrayList<>();
        for (JsonNode c : arr) {
            String in = c.get("input").isNull() ? null : c.get("input").asText();
            String exp = c.get("expected").asText();
            String got = EntityExtraction.normalizeEntityName(in);
            if (!exp.equals(got)) {
                bad.add("normalize " + show(in) + " expected " + show(exp) + " got " + show(got));
            }
        }
        check("normalize", arr.size(), bad);
    }

    @Test
    void extract() throws IOException {
        JsonNode arr = cases().get("extract");
        List<String> bad = new ArrayList<>();
        for (JsonNode c : arr) {
            String text = c.get("text").asText();
            int max = c.get("max_entities").asInt();
            List<String> terms = null;
            if (!c.get("domain_terms").isNull()) {
                terms = new ArrayList<>();
                for (JsonNode t : c.get("domain_terms")) {
                    terms.add(t.asText());
                }
            }
            List<String> exp = new ArrayList<>();
            for (JsonNode e : c.get("expected")) {
                exp.add(e.asText());
            }
            List<String> got = c.has("via_query")
                    ? EntityExtraction.extractQueryEntities(text)
                    : EntityExtraction.extractEntityCandidates(text, max, terms);
            if (!exp.equals(got)) {
                bad.add("extract " + show(text) + " max=" + max + " terms=" + terms + " expected " + show(exp)
                        + " got " + show(got));
            }
        }
        check("extract", arr.size(), bad);
    }

    @Test
    void compositeKey() throws IOException {
        JsonNode arr = cases().get("composite_key");
        List<String> bad = new ArrayList<>();
        for (JsonNode c : arr) {
            List<String> parts = new ArrayList<>();
            for (JsonNode p : c.get("parts")) {
                parts.add(p.asText());
            }
            String got = CompositeKey.of(parts.toArray(new String[0]));
            if (!c.get("expected").asText().equals(got)) {
                bad.add("composite_key " + show(parts) + " expected " + c.get("expected").asText() + " got " + got);
            }
        }
        check("composite_key", arr.size(), bad);
    }

    @Test
    void stopwords() throws IOException {
        List<String> exp = new ArrayList<>();
        for (JsonNode s : cases().get("constants").get("stopwords")) {
            exp.add(s.asText());
        }
        assertEquals(exp, new ArrayList<>(new TreeSet<>(EntityExtraction.SENTENCE_INITIAL_STOPWORDS)));
    }
}
