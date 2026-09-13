package com.ragleap.rag.vectorstore;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * One row from VectorBackend.list_documents() in base.py.
 */
public record DocumentSummary(
        String documentId, String filename, OffsetDateTime uploadedAt,
        Map<String, Object> metadata, long chunkCount
) {
}
