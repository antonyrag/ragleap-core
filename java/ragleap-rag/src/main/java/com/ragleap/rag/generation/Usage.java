package com.ragleap.rag.generation;

/**
 * Real token usage reported by a provider. Java equivalent of the
 * {"prompt_tokens", "completion_tokens", "total_tokens"} dict in
 * generation.py.
 */
public record Usage(int promptTokens, int completionTokens, int totalTokens) {
}
