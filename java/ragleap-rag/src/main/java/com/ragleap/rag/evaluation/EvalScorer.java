package com.ragleap.rag.evaluation;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Lightweight, deterministic evaluation scoring for ragleap-rag. Java
 * port of the scoring half of evaluation.py — NOT the rag.ask()-calling
 * half (see RagAnswer's javadoc for why that part is deliberately not
 * ported yet).
 *
 * Honest scope, same as the Python source: this is NOT an LLM-as-judge
 * framework - it does three deterministic, measurable checks instead:
 * retrieval hit rate, keyword coverage, and citation groundedness
 * (substring matching, not semantic understanding - a heuristic signal,
 * not proof).
 */
public final class EvalScorer {

    private static final Logger logger = Logger.getLogger(EvalScorer.class.getName());

    private EvalScorer() {
    }

    static List<String> keywordHits(String text, List<String> keywords) {
        String textLower = text.toLowerCase();
        List<String> hits = new ArrayList<>();
        for (String kw : keywords) {
            if (textLower.contains(kw.toLowerCase())) {
                hits.add(kw);
            }
        }
        return hits;
    }

    /**
     * Score a single already-produced RagAnswer against its EvalCase
     * expectations. Java equivalent of evaluate_case()'s scoring logic,
     * given the answer rag.ask() would have produced.
     */
    public static CaseResult scoreCase(EvalCase evalCase, RagAnswer answer) {
        List<String> expectedKeywords = evalCase.expectedKeywords() != null ? evalCase.expectedKeywords() : List.of();

        Boolean retrievalHit = null;
        if (evalCase.expectedDocument() != null) {
            List<String> sources = answer.sources() != null ? answer.sources() : List.of();
            retrievalHit = sources.contains(evalCase.expectedDocument());
        }

        List<String> keywordHits = keywordHits(answer.answer() != null ? answer.answer() : "", expectedKeywords);
        Double keywordCoverage = expectedKeywords.isEmpty() ? null : (double) keywordHits.size() / expectedKeywords.size();

        Double groundedness = null;
        if (!keywordHits.isEmpty()) {
            List<RagAnswer.CitationPreview> citations = answer.citations() != null ? answer.citations() : List.of();
            StringBuilder citedText = new StringBuilder();
            for (RagAnswer.CitationPreview c : citations) {
                if (citedText.length() > 0) {
                    citedText.append(" ");
                }
                citedText.append(c.textPreview() != null ? c.textPreview() : "");
            }
            List<String> groundedHits = keywordHits(citedText.toString(), keywordHits);
            groundedness = (double) groundedHits.size() / keywordHits.size();
        }

        return new CaseResult(
                evalCase.query(),
                answer.answer(),
                answer.sources() != null ? answer.sources() : List.of(),
                retrievalHit,
                keywordCoverage,
                keywordHits,
                groundedness
        );
    }

    /**
     * Aggregate a set of already-scored CaseResults into overall rates.
     * Java equivalent of evaluate()'s aggregation logic, given the
     * per-case results (produced by calling scoreCase() once per case
     * after obtaining each answer from rag.ask() - not implemented here).
     */
    public static EvaluationResult aggregate(List<CaseResult> results) {
        if (results == null || results.isEmpty()) {
            throw new IllegalArgumentException("evaluate() requires at least one test case.");
        }

        Double retrievalHitRate = average(
                results.stream().map(CaseResult::retrievalHit).filter(java.util.Objects::nonNull)
                        .map(b -> b ? 1.0 : 0.0).toList()
        );
        Double keywordCoverageRate = average(
                results.stream().map(CaseResult::keywordCoverage).filter(java.util.Objects::nonNull).toList()
        );
        Double groundednessRate = average(
                results.stream().map(CaseResult::groundedness).filter(java.util.Objects::nonNull).toList()
        );

        logger.info(() -> String.format(
                "Evaluation complete: %d cases, retrieval_hit_rate=%s, keyword_coverage_rate=%s, groundedness_rate=%s",
                results.size(), retrievalHitRate, keywordCoverageRate, groundednessRate));

        return new EvaluationResult(retrievalHitRate, keywordCoverageRate, groundednessRate, results);
    }

    private static Double average(List<Double> values) {
        if (values.isEmpty()) {
            return null;
        }
        double sum = 0.0;
        for (double v : values) {
            sum += v;
        }
        return sum / values.size();
    }
}
