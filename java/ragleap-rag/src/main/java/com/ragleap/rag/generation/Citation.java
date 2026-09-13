package com.ragleap.rag.generation;

/**
 * Structured citation mapping a [Source N] label used in the prompt to
 * the specific chunk it refers to. Java port of ragleap-rag's
 * generation.py - GenerationService._build_citations()'s dict shape.
 *
 * Always chunk-level, never document-level - resolves the ambiguity
 * of whether a citation like "(Source 1)" in an answer means a whole
 * document or a specific passage. It is always the latter.
 */
public record Citation(
        int sourceNumber, String documentName, String documentId,
        String chunkId, int chunkIndex, String textPreview
) {
}
