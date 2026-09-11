package com.ragleap.rag.evaluation;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class EvalScorerTest {

    @Test
    void retrievalHitTrueWhenExpectedDocumentInSources() {
        EvalCase evalCase = new EvalCase("who founded ragleap?", "founders.md", List.of());
        RagAnswer answer = new RagAnswer("Antony founded RagLeap.", List.of("founders.md", "about.md"), List.of());

        CaseResult result = EvalScorer.scoreCase(evalCase, answer);
        assertEquals(Boolean.TRUE, result.retrievalHit());
    }

    @Test
    void retrievalHitFalseWhenExpectedDocumentMissing() {
        EvalCase evalCase = new EvalCase("who founded ragleap?", "founders.md", List.of());
        RagAnswer answer = new RagAnswer("Antony founded RagLeap.", List.of("about.md"), List.of());

        CaseResult result = EvalScorer.scoreCase(evalCase, answer);
        assertEquals(Boolean.FALSE, result.retrievalHit());
    }

    @Test
    void retrievalHitNullWhenNoExpectedDocument() {
        EvalCase evalCase = new EvalCase("what is ragleap?", null, List.of());
        RagAnswer answer = new RagAnswer("A RAG platform.", List.of("about.md"), List.of());

        assertNull(EvalScorer.scoreCase(evalCase, answer).retrievalHit());
    }

    @Test
    void keywordCoveragePartialMatch() {
        EvalCase evalCase = new EvalCase("what channels?", null, List.of("whatsapp", "telegram", "fax"));
        RagAnswer answer = new RagAnswer("We support WhatsApp and Telegram.", List.of(), List.of());

        CaseResult result = EvalScorer.scoreCase(evalCase, answer);
        assertEquals(2.0 / 3.0, result.keywordCoverage(), 0.000001);
        assertEquals(List.of("whatsapp", "telegram"), result.keywordsFound());
    }

    @Test
    void keywordCoverageNullWhenNoExpectedKeywords() {
        EvalCase evalCase = new EvalCase("hello", null, List.of());
        RagAnswer answer = new RagAnswer("hi there", List.of(), List.of());

        assertNull(EvalScorer.scoreCase(evalCase, answer).keywordCoverage());
    }

    @Test
    void groundednessComputedFromCitedText() {
        EvalCase evalCase = new EvalCase("q", null, List.of("gemini", "openai"));
        RagAnswer answer = new RagAnswer(
                "We support Gemini and OpenAI.",
                List.of(),
                List.of(new RagAnswer.CitationPreview("RagLeap integrates with Gemini for embeddings."))
        );

        CaseResult result = EvalScorer.scoreCase(evalCase, answer);
        // "gemini" found in cited text, "openai" found in answer but not cited
        assertEquals(0.5, result.groundedness(), 0.000001);
    }

    @Test
    void groundednessNullWhenNoKeywordHits() {
        EvalCase evalCase = new EvalCase("q", null, List.of("nonexistent"));
        RagAnswer answer = new RagAnswer("unrelated answer", List.of(), List.of());

        assertNull(EvalScorer.scoreCase(evalCase, answer).groundedness());
    }

    @Test
    void aggregateComputesRatesAcrossCases() {
        CaseResult r1 = new CaseResult("q1", "a1", List.of(), true, 1.0, List.of("k1"), 1.0);
        CaseResult r2 = new CaseResult("q2", "a2", List.of(), false, 0.5, List.of("k1"), 0.0);

        EvaluationResult result = EvalScorer.aggregate(List.of(r1, r2));

        assertEquals(0.5, result.retrievalHitRate(), 0.000001);
        assertEquals(0.75, result.keywordCoverageRate(), 0.000001);
        assertEquals(0.5, result.groundednessRate(), 0.000001);
        assertEquals(2, result.results().size());
    }

    @Test
    void aggregateRatesNullWhenNoCaseContributesThatMetric() {
        CaseResult r1 = new CaseResult("q1", "a1", List.of(), null, null, List.of(), null);

        EvaluationResult result = EvalScorer.aggregate(List.of(r1));

        assertNull(result.retrievalHitRate());
        assertNull(result.keywordCoverageRate());
        assertNull(result.groundednessRate());
    }

    @Test
    void aggregateThrowsOnEmptyResults() {
        assertThrows(IllegalArgumentException.class, () -> EvalScorer.aggregate(List.of()));
    }
}
