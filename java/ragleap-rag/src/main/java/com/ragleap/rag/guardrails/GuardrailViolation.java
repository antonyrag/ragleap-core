package com.ragleap.rag.guardrails;

/**
 * Throw this from a guardrail function to reject content.
 * Java port of ragleap-rag's guardrails.py — GuardrailViolation.
 *
 * For input guardrails, this aborts ingestion - nothing is stored.
 * For output guardrails on the (not yet ported) non-streaming ask(),
 * this replaces the answer with a refusal message before it's
 * returned. For the (not yet ported) streaming ask_stream(), by the
 * time this fires, individual tokens may have already been yielded to
 * the caller — that streaming-vs-non-streaming enforcement distinction
 * lives in the caller, not in this class or in GuardrailRunner below.
 */
public class GuardrailViolation extends RuntimeException {
    public GuardrailViolation(String message) {
        super(message);
    }
}
