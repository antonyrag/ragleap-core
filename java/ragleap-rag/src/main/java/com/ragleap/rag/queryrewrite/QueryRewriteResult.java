package com.ragleap.rag.queryrewrite;

import com.ragleap.rag.generation.GenerationResult;

/**
 * (query_to_use_for_retrieval, raw_generate_answer_result_or_None)
 * from query_rewrite.py's contextual_rewrite()/hyde_document(). Java
 * has no tuple type, and this project already has a proper typed
 * result for what Python calls a raw dict - GenerationResult - so
 * rawResult is that directly rather than a generic Map, a deliberate
 * improvement the Java port can make for free.
 */
public record QueryRewriteResult(String query, GenerationResult rawResult) {
}
