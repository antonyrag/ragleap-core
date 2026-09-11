package com.ragleap.rag.structured;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Result of validating structured output against a schema. Java
 * equivalent of the (parsed_object_or_None, is_valid, validation_method)
 * tuple returned by structured.py.
 *
 * parsed is null when raw_text failed to parse as JSON at all - this
 * never throws, matching the Python source's "never raises" contract.
 */
public record ValidationResult(JsonNode parsed, boolean valid, ValidationMethod method) {
}
