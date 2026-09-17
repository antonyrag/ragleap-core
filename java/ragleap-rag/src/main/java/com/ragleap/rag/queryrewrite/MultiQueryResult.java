package com.ragleap.rag.queryrewrite;

import com.ragleap.rag.generation.GenerationResult;

import java.util.List;

/**
 * (list_of_query_variants, raw_generate_answer_result_or_None) from
 * query_rewrite.py's multi_query_variants().
 */
public record MultiQueryResult(List<String> variants, GenerationResult rawResult) {
}
