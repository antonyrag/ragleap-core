package com.ragleap.rag.retrieval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ragleap.rag.db.ConnectionPool;
import com.ragleap.rag.vectorstore.SearchResult;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.StringJoiner;
import java.util.UUID;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Retrieval for ragleap-rag: dense (pgvector), sparse (Postgres
 * full-text), and hybrid (Reciprocal Rank Fusion) search. Java port of
 * ragleap-rag's retrieval.py - VectorRetrievalService.
 *
 * Requires a PostgreSQL database with the pgvector extension and the
 * schema created by com.ragleap.rag.schema.SchemaManager (see that
 * class for the exact DDL).
 *
 * No knowledge-graph coupling here by design - ragleap-graph (a
 * separate package, not yet ported) extends retrieval with
 * graph-boosted ranking on top of this.
 *
 * Deliberate overlap with com.ragleap.rag.vectorstore.PgVectorBackend,
 * documented rather than silently duplicated or refactored away: this
 * class predates/parallels the VectorBackend abstraction in the Python
 * source (operates on a raw pool directly, not through an interface)
 * and has real behavioral differences from PgVectorBackend worth
 * preserving faithfully:
 *   - Validates query embedding dimensions match the configured
 *     embeddingDimensions exactly, warning and returning empty rather
 *     than proceeding on mismatch - PgVectorBackend has no such check.
 *   - Supports filtering to a single documentId - PgVectorBackend only
 *     supports metadata filtering, not a document_id filter.
 *   - Logs and RE-THROWS on error (via SEVERE + rethrow) rather than
 *     letting the checked exception propagate unlogged.
 */
public class VectorRetrievalService {

    private static final Logger logger = Logger.getLogger(VectorRetrievalService.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final int RRF_K = 60; // Reciprocal Rank Fusion constant - 60 is the standard default.

    private final ConnectionPool pool;
    private final int embeddingDimensions;
    private final double minSimilarity;

    public VectorRetrievalService(ConnectionPool pool) {
        this(pool, 3072, 0.05);
    }

    public VectorRetrievalService(ConnectionPool pool, int embeddingDimensions, double minSimilarity) {
        this.pool = pool;
        this.embeddingDimensions = embeddingDimensions;
        this.minSimilarity = minSimilarity;
    }

    /** Dense retrieval via pgvector cosine distance. */
    public List<SearchResult> searchSimilarChunks(List<Double> queryEmbedding, int topK,
                                                     String documentId, Map<String, Object> metadataFilter) throws SQLException {
        if (queryEmbedding == null || queryEmbedding.isEmpty()) {
            return List.of();
        }
        if (queryEmbedding.size() != embeddingDimensions) {
            logger.warning(() -> String.format(
                    "Query embedding dim=%d != expected %d; skipping search",
                    queryEmbedding.size(), embeddingDimensions));
            return List.of();
        }

        String literal = toVectorLiteral(queryEmbedding);

        StringBuilder sql = new StringBuilder(String.format(
                "SELECT id, text, document_id, document_name, chunk_index, " +
                "1 - (embedding::halfvec(%1$d) <=> ?::halfvec(%1$d)) / 2 AS similarity_score " +
                "FROM chunks", embeddingDimensions));

        List<String> whereClauses = new ArrayList<>();
        if (documentId != null) {
            whereClauses.add("document_id = ?");
        }
        boolean hasMetadataFilter = metadataFilter != null && !metadataFilter.isEmpty();
        if (hasMetadataFilter) {
            whereClauses.add("metadata @> ?::jsonb");
        }
        if (!whereClauses.isEmpty()) {
            sql.append(" WHERE ").append(String.join(" AND ", whereClauses));
        }
        sql.append(String.format(" ORDER BY embedding::halfvec(%1$d) <=> ?::halfvec(%1$d) LIMIT ?", embeddingDimensions));

        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(sql.toString())) {
            int i = 1;
            stmt.setString(i++, literal);
            if (documentId != null) {
                stmt.setObject(i++, UUID.fromString(documentId));
            }
            if (hasMetadataFilter) {
                stmt.setString(i++, toJson(metadataFilter));
            }
            stmt.setString(i++, literal);
            stmt.setInt(i, topK);

            List<SearchResult> results = new ArrayList<>();
            try (ResultSet rs = stmt.executeQuery()) {
                while (rs.next()) {
                    double score = rs.getDouble("similarity_score");
                    if (score < minSimilarity) {
                        continue;
                    }
                    results.add(new SearchResult(
                            rs.getObject("id", UUID.class).toString(),
                            rs.getString("text"),
                            Math.round(score * 10000.0) / 10000.0,
                            rs.getObject("document_id", UUID.class).toString(),
                            rs.getString("document_name"),
                            rs.getInt("chunk_index")
                    ));
                }
            }
            int finalTopK = topK;
            logger.info(() -> String.format("Vector search returned %d chunks (top_k=%d)", results.size(), finalTopK));
            return results;
        } catch (SQLException e) {
            logger.log(Level.SEVERE, "Vector search error: " + e.getMessage(), e);
            throw e;
        }
    }

    /** Sparse (keyword/full-text) retrieval via Postgres text search. */
    public List<SearchResult> searchSparseChunks(String queryText, int topK,
                                                    String documentId, Map<String, Object> metadataFilter) throws SQLException {
        if (queryText == null || queryText.isBlank()) {
            return List.of();
        }

        StringBuilder sql = new StringBuilder(
                "SELECT id, text, document_id, document_name, chunk_index, " +
                "ts_rank(text_search_vector, websearch_to_tsquery('english', ?)) AS rank_score " +
                "FROM chunks " +
                "WHERE text_search_vector @@ websearch_to_tsquery('english', ?)");

        if (documentId != null) {
            sql.append(" AND document_id = ?");
        }
        boolean hasMetadataFilter = metadataFilter != null && !metadataFilter.isEmpty();
        if (hasMetadataFilter) {
            sql.append(" AND metadata @> ?::jsonb");
        }
        sql.append(" ORDER BY rank_score DESC LIMIT ?");

        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(sql.toString())) {
            int i = 1;
            stmt.setString(i++, queryText);
            stmt.setString(i++, queryText);
            if (documentId != null) {
                stmt.setObject(i++, UUID.fromString(documentId));
            }
            if (hasMetadataFilter) {
                stmt.setString(i++, toJson(metadataFilter));
            }
            stmt.setInt(i, topK);

            List<SearchResult> results = new ArrayList<>();
            try (ResultSet rs = stmt.executeQuery()) {
                while (rs.next()) {
                    results.add(new SearchResult(
                            rs.getObject("id", UUID.class).toString(),
                            rs.getString("text"),
                            Math.round(rs.getDouble("rank_score") * 10000.0) / 10000.0,
                            rs.getObject("document_id", UUID.class).toString(),
                            rs.getString("document_name"),
                            rs.getInt("chunk_index")
                    ));
                }
            }
            int finalTopK = topK;
            logger.info(() -> String.format("Sparse search returned %d chunks (top_k=%d)", results.size(), finalTopK));
            return results;
        } catch (SQLException e) {
            logger.log(Level.SEVERE, "Sparse search error: " + e.getMessage(), e);
            throw e;
        }
    }

    /**
     * Combines dense + sparse via Reciprocal Rank Fusion. similarityScore
     * in the returned results is the RRF-fused score, meaningful only for
     * ranking within this result set (not a 0-1 cosine similarity).
     */
    public List<SearchResult> searchHybridChunks(String queryText, List<Double> queryEmbedding, int topK,
                                                    String documentId, Map<String, Object> metadataFilter) throws SQLException {
        List<SearchResult> dense = searchSimilarChunks(queryEmbedding, topK * 3, documentId, metadataFilter);
        List<SearchResult> sparse = searchSparseChunks(queryText, topK * 3, documentId, metadataFilter);

        Map<String, Integer> denseRanks = new LinkedHashMap<>();
        for (int i = 0; i < dense.size(); i++) {
            denseRanks.put(dense.get(i).chunkId(), i);
        }
        Map<String, Integer> sparseRanks = new LinkedHashMap<>();
        for (int i = 0; i < sparse.size(); i++) {
            sparseRanks.put(sparse.get(i).chunkId(), i);
        }

        Map<String, SearchResult> lookup = new LinkedHashMap<>();
        for (SearchResult c : dense) {
            lookup.put(c.chunkId(), c);
        }
        for (SearchResult c : sparse) {
            lookup.putIfAbsent(c.chunkId(), c);
        }

        Set<String> allIds = new LinkedHashSet<>();
        allIds.addAll(denseRanks.keySet());
        allIds.addAll(sparseRanks.keySet());
        if (allIds.isEmpty()) {
            return List.of();
        }

        Map<String, Double> rrfScores = new LinkedHashMap<>();
        for (String cid : allIds) {
            double score = 0.0;
            if (denseRanks.containsKey(cid)) {
                score += 1.0 / (RRF_K + denseRanks.get(cid) + 1);
            }
            if (sparseRanks.containsKey(cid)) {
                score += 1.0 / (RRF_K + sparseRanks.get(cid) + 1);
            }
            rrfScores.put(cid, score);
        }

        List<SearchResult> results = new ArrayList<>();
        for (String cid : allIds) {
            SearchResult base = lookup.get(cid);
            double score = Math.round(rrfScores.get(cid) * 1_000_000.0) / 1_000_000.0;
            results.add(new SearchResult(base.chunkId(), base.text(), score,
                    base.documentId(), base.documentName(), base.chunkIndex(), "hybrid_rrf"));
        }
        results.sort((a, b) -> Double.compare(b.similarityScore(), a.similarityScore()));

        List<SearchResult> topResults = results.size() > topK ? results.subList(0, topK) : results;
        int denseSize = dense.size();
        int sparseSize = sparse.size();
        int fusedSize = results.size();
        int returned = topResults.size();
        logger.info(() -> String.format(
                "Hybrid search: %d dense + %d sparse -> %d fused, returning top %d",
                denseSize, sparseSize, fusedSize, returned));

        return topResults;
    }

    private static String toVectorLiteral(List<Double> embedding) {
        StringJoiner joiner = new StringJoiner(",", "[", "]");
        for (Double v : embedding) {
            joiner.add(String.valueOf(v));
        }
        return joiner.toString();
    }

    private static String toJson(Map<String, Object> map) throws SQLException {
        try {
            return MAPPER.writeValueAsString(map != null ? map : Map.of());
        } catch (Exception e) {
            throw new SQLException("Failed to serialize metadata to JSON", e);
        }
    }
}
