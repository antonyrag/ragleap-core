package com.ragleap.rag.vectorstore;

import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Every vector storage backend must implement this interface. Java
 * port of ragleap-rag's vectorstores/base.py - VectorBackend.
 *
 * RagLeap defaults to PgVectorBackend (Postgres + pgvector) for full
 * backward compatibility. Other backends (FAISS, Pinecone, ...) can be
 * swapped in later. Backends differ in what they can do -
 * supportsSparse() is a real capability flag, not a formality: callers
 * should check it before assuming hybrid search is meaningful for a
 * given backend.
 *
 * Methods declare `throws SQLException` rather than the Java
 * equivalent of Python's bare exceptions - JDBC operations are
 * inherently checked-exception-bearing, and callers need to see that
 * in the interface, unlike Python where any exception can propagate
 * silently through an unannotated method signature.
 */
public interface VectorBackend {

    /** Create/verify whatever storage structure this backend needs. Idempotent. */
    void initSchema(int dimensions) throws SQLException;

    /** Register a new document (parent record for its chunks). */
    void insertDocument(String documentId, String filename, Map<String, Object> metadata) throws SQLException;

    /** Store one chunk with its embedding. */
    void insertChunk(String documentId, String documentName, int chunkIndex, String text,
                       Integer tokenCount, List<Double> embedding, Map<String, Object> metadata) throws SQLException;

    /**
     * Vector similarity search. Must return results with at least
     * chunkId, text, similarityScore, documentId, documentName, chunkIndex.
     */
    List<SearchResult> searchDense(List<Double> embedding, int topK, Map<String, Object> metadataFilter) throws SQLException;

    /** Keyword/full-text search. Default: not supported (see supportsSparse()). */
    default List<SearchResult> searchSparse(String queryText, int topK, Map<String, Object> metadataFilter) throws SQLException {
        return List.of();
    }

    /**
     * Combined dense+sparse via RRF. Default: falls back to dense-only
     * if this backend doesn't support sparse search - see supportsSparse().
     */
    default List<SearchResult> searchHybrid(String queryText, List<Double> embedding, int topK,
                                              Map<String, Object> metadataFilter) throws SQLException {
        return searchDense(embedding, topK, metadataFilter);
    }

    /**
     * Whether this backend can do real keyword/full-text search.
     * Callers should check this rather than assume hybrid search is
     * doing anything beyond dense search under the hood.
     */
    default boolean supportsSparse() {
        return false;
    }

    /** List documents, most recent first. */
    List<DocumentSummary> listDocuments(int limit, int offset) throws SQLException;

    /** Delete a document and its chunks. Returns true if something was deleted. */
    boolean deleteDocument(String documentId) throws SQLException;

    /**
     * Return a document's stored filename, or empty if it doesn't exist.
     * Used when no explicit filename is given for an update.
     */
    Optional<String> getDocumentFilename(String documentId) throws SQLException;
}
