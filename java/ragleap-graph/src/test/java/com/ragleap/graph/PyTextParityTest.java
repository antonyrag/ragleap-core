package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Compares lower-casing and code point ordering with Python's behaviour. */
@EnabledIfEnvironmentVariable(named = "RAGLEAP_GRAPH_PARITY_DIR", matches = ".+")
class PyTextParityTest {
    private static JsonNode cases() throws IOException {
        Path dir = Path.of(System.getenv("RAGLEAP_GRAPH_PARITY_DIR"));
        return new ObjectMapper().readTree(dir.resolve("lower_cases.json").toFile());
    }

    private static String show(String s) {
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

    @Test
    void lowerMatchesPython() throws IOException {
        JsonNode arr = cases().get("lower");
        List<String> bad = new ArrayList<>();
        for (JsonNode c : arr) {
            String in = c.get("input").asText();
            String exp = c.get("expected").asText();
            String got = PyText.lower(in);
            if (!exp.equals(got)) {
                bad.add("lower " + show(in) + " expected " + show(exp) + " got " + show(got));
            }
        }
        assertTrue(bad.isEmpty(), arr.size() + " cases, " + bad.size() + " mismatches:\n" + String.join("\n", bad));
    }

    @Test
    void codePointOrderMatchesPython() throws IOException {
        List<String> expected = new ArrayList<>();
        for (JsonNode s : cases().get("order")) {
            expected.add(s.asText());
        }
        List<String> copy = new ArrayList<>(expected);
        Collections.reverse(copy);
        copy.sort(PyText::compareCodePoints);
        assertEquals(expected, copy);
    }
}
