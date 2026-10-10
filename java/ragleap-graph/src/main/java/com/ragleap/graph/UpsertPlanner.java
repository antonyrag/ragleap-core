package com.ragleap.graph;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Pure planning step of upsertDocument: counts entities and entity pairs per chunk and picks the top ones,
 * exactly as the Python implementation does (regex extraction only; LLM relations come in a later slice).
 */
final class UpsertPlanner {
    private UpsertPlanner() {
    }

    record PairKey(String a, String b) {
    }

    record RelKey(String subject, String relationType, String object) {
    }

    record RelationEntry(String subject, String relationType, String object, int count) {
    }

    record Plan(List<Map.Entry<String, Integer>> topEntities, Map<String, String> entityTypes,
                List<Map.Entry<PairKey, Integer>> topPairs, List<RelationEntry> topRelations) {
    }

    static Plan plan(List<Map<String, Object>> chunks, int maxEntities, int maxPairs, List<String> domainTerms) {
        Map<String, Integer> entityCounter = new LinkedHashMap<>();
        Map<PairKey, Integer> pairCounter = new LinkedHashMap<>();
        Map<String, String> entityTypes = new HashMap<>();
        if (chunks != null) {
            for (Map<String, Object> chunk : chunks) {
                Object raw = chunk.get("text");
                String text = raw == null ? "" : PyText.strip(raw.toString());
                if (text.isEmpty()) {
                    continue;
                }
                List<String> names = EntityExtraction.extractEntityCandidates(text, 12, domainTerms);
                if (names.isEmpty()) {
                    continue;
                }
                List<String> unique = new ArrayList<>();
                Set<String> seen = new HashSet<>();
                for (String ent : names) {
                    String key = PyText.lower(ent);
                    if (!seen.add(key)) {
                        continue;
                    }
                    unique.add(ent);
                    entityCounter.merge(ent, 1, Integer::sum);
                    entityTypes.putIfAbsent(key, "UNKNOWN");
                }
                for (int i = 0; i < unique.size(); i++) {
                    for (int j = i + 1; j < unique.size(); j++) {
                        String a = unique.get(i);
                        String b = unique.get(j);
                        if (a.equals(b)) {
                            continue;
                        }
                        pairCounter.merge(orderByLower(a, b), 1, Integer::sum);
                    }
                }
            }
        }
        return new Plan(mostCommon(entityCounter, maxEntities), entityTypes,
                mostCommon(pairCounter, maxPairs), List.of());
    }

    /** Python: tuple(sorted((a, b), key=lambda s: s.lower())). */
    static PairKey orderByLower(String a, String b) {
        return PyText.compareCodePoints(PyText.lower(a), PyText.lower(b)) <= 0 ? new PairKey(a, b) : new PairKey(b, a);
    }

    /** Python Counter.most_common(n): highest counts first, first-seen order kept on ties. */
    static <K> List<Map.Entry<K, Integer>> mostCommon(Map<K, Integer> counter, int n) {
        List<Map.Entry<K, Integer>> items = new ArrayList<>();
        for (Map.Entry<K, Integer> e : counter.entrySet()) {
            items.add(Map.entry(e.getKey(), e.getValue()));
        }
        items.sort((x, y) -> Integer.compare(y.getValue(), x.getValue()));
        return new ArrayList<>(items.subList(0, Math.min(Math.max(n, 0), items.size())));
    }
}
