package com.ragleap.rag.vectorstore;

/**
 * One search hit. Java equivalent of the dicts returned by
 * VectorBackend.search_dense()/search_sparse()/search_hybrid() in
 * base.py - must contain at least chunk_id, text, similarity_score,
 * document_id, document_name, chunk_index.
 *
 * retrievalMethod is null for plain dense/sparse results - only
 * search_hybrid() sets it, to "hybrid_rrf".
 */
public record SearchResult(
        String chunkId, String text, double similarityScore,
        String documentId, String documentName, int chunkIndex,
        String retrievalMethod
) {
    public SearchResult(String chunkId, String text, double similarityScore,
                          String documentId, String documentName, int chunkIndex) {
        this(chunkId, text, similarityScore, documentId, documentName, chunkIndex, null);
    }
}
