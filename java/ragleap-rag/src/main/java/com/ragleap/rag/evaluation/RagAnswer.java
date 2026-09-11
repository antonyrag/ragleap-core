package com.ragleap.rag.evaluation;

import java.util.List;

/**
 * An already-produced answer from a RAG pipeline - the Java equivalent
 * of the dict returned by rag.ask() in the Python source, which
 * evaluation.py's evaluate_case()/evaluate() call directly.
 *
 * NOT PORTED HERE: the actual rag.ask() call itself. That requires the
 * not-yet-ported retrieval + generation pipeline (real LLM API calls),
 * same category of external dependency as db.py's ConnectionPool. This
 * class exists so the deterministic scoring logic below (EvalScorer)
 * can be ported and genuinely unit-tested now, decoupled from producing
 * the answer - once rag.ask() exists in Java, its result maps to this
 * record and scoreCase()/evaluate() work unchanged.
 */
public record RagAnswer(String answer, List<String> sources, List<CitationPreview> citations) {

    public record CitationPreview(String textPreview) {
    }
}
