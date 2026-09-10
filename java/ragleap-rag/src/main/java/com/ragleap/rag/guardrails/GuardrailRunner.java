package com.ragleap.rag.guardrails;

import java.util.List;
import java.util.function.UnaryOperator;

/**
 * Guardrail hooks for ragleap-rag - user-supplied validation callbacks
 * for ingested content (input guardrails) and generated answers
 * (output guardrails). Java port of ragleap-rag's guardrails.py.
 *
 * This extends the existing sanitization module (see
 * com.ragleap.rag.sanitization.ContentSanitizer for null-byte
 * stripping and injection-risk heuristics) rather than replacing it -
 * guardrails run in addition to, after, that baseline.
 *
 * Unlike ObservabilityHooks, guardrails are NOT fire-and-forget: no
 * exception is caught here. A guardrail throwing (whether
 * GuardrailViolation or anything else) propagates straight through to
 * the caller - matching the Python source exactly, which has no
 * try/except around the guardrail call.
 */
public final class GuardrailRunner {

    private GuardrailRunner() {
    }

    /**
     * Run each guardrail in order, threading the (possibly modified)
     * text through each one. A guardrail can either return a (possibly
     * transformed) string, or throw GuardrailViolation to reject the
     * content outright.
     */
    public static String runGuardrails(String text, List<UnaryOperator<String>> guardrails) {
        if (guardrails == null || guardrails.isEmpty()) {
            return text;
        }
        String result = text;
        for (UnaryOperator<String> guardrail : guardrails) {
            result = guardrail.apply(result);
        }
        return result;
    }
}
