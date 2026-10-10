package com.ragleap.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class GraphQueryTest {
    private static GraphIndex unavailable() {
        return new GraphIndex((CypherRunner) null, null, s -> { });
    }

    private static Map<String, Object> row(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    @Test
    void depthAndDirectionAreCheckedEvenWhenUnavailable() {
        GraphIndex g = unavailable();
        assertEquals("max_depth must be between 1 and 10, got 0", assertThrows(IllegalArgumentException.class,
                () -> g.searchRelatedEntities(List.of("Acme Corp"), null, null, 0, 10)).getMessage());
        assertEquals("max_depth must be between 1 and 10, got 11", assertThrows(IllegalArgumentException.class,
                () -> g.searchRelatedEntities(List.of("Acme Corp"), null, null, 11, 10)).getMessage());
        assertEquals("direction must be \"outgoing\", \"incoming\", or \"both\", got 'sideways'",
                assertThrows(IllegalArgumentException.class,
                        () -> g.findRelations("Acme Corp", null, null, null, 25, "sideways")).getMessage());
        assertEquals("direction must be \"outgoing\", \"incoming\", or \"both\", got None",
                assertThrows(IllegalArgumentException.class,
                        () -> g.findRelations("Acme Corp", null, null, null, 25, null)).getMessage());
    }

    @Test
    void unavailableIndexReturnsEmptyResults() {
        GraphIndex g = unavailable();
        assertTrue(g.searchRelatedEntities(List.of("Acme Corp")).isEmpty());
        assertTrue(g.findRelations("Acme Corp").isEmpty());
        assertTrue(g.findLineage("Acme Corp", "Globex Corp").isEmpty());
        assertTrue(g.findEntitiesByType("ORG").isEmpty());
    }

    @Test
    void blankAndInvalidInputsSkipTheQuery() {
        GraphIndexTest.Scripted r = new GraphIndexTest.Scripted();
        GraphIndex g = new GraphIndex(r, null, s -> { });
        int before = r.cyphers.size();
        assertTrue(g.searchRelatedEntities(List.of("ab", "", "  ")).isEmpty());
        assertTrue(g.findRelations("  ").isEmpty());
        assertTrue(g.findRelations("ab").isEmpty());
        assertTrue(g.findLineage("  ", "Globex").isEmpty());
        assertTrue(g.findLineage("Acme", "").isEmpty());
        assertTrue(g.findEntitiesByType("   ").isEmpty());
        assertEquals(before, r.cyphers.size());
    }

    @Test
    void depthIsFormattedIntoTheQuery() {
        GraphIndexTest.Scripted r = new GraphIndexTest.Scripted();
        GraphIndex g = new GraphIndex(r, null, s -> { });
        g.searchRelatedEntities(List.of("Acme Corp"), "n", null, 3, 10);
        String last = r.cyphers.get(r.cyphers.size() - 1);
        assertTrue(last.contains("[*1..3]"), last);
        assertFalse(last.contains("{max_depth}"), last);
    }

    @Test
    void lineageIsCutToTheLimitButAuditsTheFullCount() {
        GraphIndexTest.Scripted r = new GraphIndexTest.Scripted();
        r.rows = c -> c.contains("MATCH (pw:PairWeight")
                ? List.of(row("document_id", "d1", "weight", 1.0), row("document_id", "d2", "weight", 2.0),
                        row("document_id", "d3", "weight", 3.0))
                : List.of();
        List<Map<String, Object>> details = new ArrayList<>();
        GraphIndex g = new GraphIndex(r, (u, n, a, d, cnt, detail) -> details.add(detail), s -> { });
        List<LineageEntry> result = g.findLineage("Acme Corp", "Globex Corp", null, "n", null, 2);
        assertEquals(2, result.size());
        assertEquals("d1", result.get(0).documentId());
        assertEquals("CO_OCCURS_WITH", result.get(0).relationType());
        assertEquals(1.0, result.get(0).weight().doubleValue());
        assertEquals(3, details.get(0).get("result_count"));
    }

    @Test
    void queryErrorsReturnEmptyResults() {
        GraphIndexTest.Scripted r = new GraphIndexTest.Scripted();
        GraphIndex g = new GraphIndex(r, null, s -> { });
        r.failure = c -> c.startsWith("MATCH") ? new GraphException("x") : null;
        assertTrue(g.searchRelatedEntities(List.of("Acme Corp")).isEmpty());
        assertTrue(g.findRelations("Acme Corp").isEmpty());
        assertTrue(g.findLineage("Acme Corp", "Globex Corp").isEmpty());
        assertTrue(g.findEntitiesByType("ORG").isEmpty());
    }
}
