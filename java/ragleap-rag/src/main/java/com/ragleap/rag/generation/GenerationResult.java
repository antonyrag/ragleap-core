package com.ragleap.rag.generation;

import com.fasterxml.jackson.databind.JsonNode;
import com.ragleap.rag.structured.ValidationMethod;

import java.util.List;

/**
 * Result of GenerationService.generateAnswer(). Java equivalent of the
 * dict returned by generate_answer() in generation.py.
 *
 * The structured* fields are null unless a responseFormat schema was
 * passed to generateAnswer() - matching the Python source, which only
 * adds those keys to the result dict when response_format is not None.
 */
public record GenerationResult(
        String answer, List<String> sources, List<Citation> citations,
        String providerUsed, String modelUsed, Usage usage, int chunksSent,
        JsonNode structured, Boolean structuredValid, String structuredEnforcement,
        ValidationMethod structuredValidationMethod
) {
}
