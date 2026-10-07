package com.ragleap.rag.ingestion;

/**
 * Describes an image in text (vision captioning), for IngestionService's "caption" mode. A vision-capable
 * GenerationService fits directly: {@code generation::describeImage}.
 */
@FunctionalInterface
public interface ImageDescriber {

    String describe(byte[] imageBytes, String mimeType) throws Exception;
}
