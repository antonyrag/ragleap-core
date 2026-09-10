package com.ragleap.rag.chunker;

/**
 * A single text chunk produced by TextChunker, with token-count metadata.
 * Java equivalent of the dict returned per-chunk by chunker.py's chunk_text().
 */
public record Chunk(String text, int chunkIndex, int tokenCount, boolean tokenCountIsExact) {
}
