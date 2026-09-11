package com.ragleap.rag.evaluation;

import java.util.List;

/**
 * Per-case scoring detail. Java equivalent of the dict returned by
 * evaluate_case() in evaluation.py.
 *
 * Boolean/Double (boxed) fields use null the same way Python uses None -
 * to mean "not applicable to this case" (e.g. retrievalHit is null when
 * the case had no expectedDocument), not "false"/"0.0".
 */
public record CaseResult(
        String query,
        String answer,
        List<String> sources,
        Boolean retrievalHit,
        Double keywordCoverage,
        List<String> keywordsFound,
        Double groundedness
) {
}
