package com.ragleap.rag.evaluation;

import java.util.List;

/**
 * Aggregated evaluation result. Java equivalent of evaluate()'s return
 * dict in evaluation.py. The three rate fields are null when no case
 * contributed a value for that metric - matching Python's None, not 0.0.
 */
public record EvaluationResult(
        Double retrievalHitRate,
        Double keywordCoverageRate,
        Double groundednessRate,
        List<CaseResult> results
) {
}
