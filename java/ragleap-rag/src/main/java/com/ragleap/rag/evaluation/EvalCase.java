package com.ragleap.rag.evaluation;

import java.util.List;

/**
 * A single evaluation test case, mirroring cost.py's EvalCase TypedDict
 * from ragleap-rag's evaluation.py.
 */
public record EvalCase(String query, String expectedDocument, List<String> expectedKeywords) {
    public EvalCase(String query) {
        this(query, null, List.of());
    }
}
