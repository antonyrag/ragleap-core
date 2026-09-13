package com.ragleap.rag.vectorstore;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ragleap.rag.db.ConnectionPool;
import com.ragleap.rag.schema.SchemaManager;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.StringJoiner;
import java.util.UUID;

/**
 * Postgres + pgvector backend - the default, battle-tested storage for
 * ragleap-rag. Java port of ragleap-rag's vectorstores/pgvector.py -
 * PgVectorBackend.
 *
 * This PR ports the CRUD + dense-search half only (initSchema,
 * insertDocument, insertChunk, searchDense, listDocuments,
 * deleteDocument, getDocumentFilename). searchSparse and searchHybrid
 * (RRF fusion) are a deliberate follow-up PR.
 *
 * Key technical note: pgvector's halfvec(N) type-modifier position
 * must be a literal at SQL-parse time, not a JDBC bind parameter -
 * PreparedStatement can't put a `?` inside `halfvec(?)`. This mirrors
 * what psycopg2's %s effectively did too (client-side string
 * substitution before the query is sent), just via a different
 * mechanism - dimensions is interpolated directly into the SQL text
 * (safe here: it's an internal int, never user input), while every
 * actual data value still uses a real bind parameter.
 *
 * Metadata (JSONB) is serialized/deserialized explicitly via Jackson's
 * ObjectMapper - unlike psycopg2, the JDBC PostgreSQL driver doesn't
 * auto-parse jsonb columns into a Map.
 *
 * document_id and chunk id map to java.util.UUID via JDBC's native
 * support, rather than string-casting the way Python's implicit
 * str(uuid_obj) coercion does - a deliberate improvement, documented
 * here rather than silently diverging.
 */
public class PgVectorBackend implements VectorBackend {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final ConnectionPool pool;
    private final double minSimilarity;
    private Integer dimensions;

    public PgVectorBackend(String databaseUrl) {
        this(databaseUrl, 0.05);
    }

    public PgVectorBackend(String databaseUrl, double minSimilarity) {
        this.pool = new ConnectionPool(databaseUrl);
        this.minSimilarity = minSimilarity;
    }

    @Override
    public void initSchema(int dimensions) throws SQLException {
        this.dimensions = dimensions;
        SchemaManager.initCoreSchema(pool, dimensions);
    }

    @Override
    public void insertDocument(String documentId, String filename, Map<String, Object> metadata) throws SQLException {
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "INSERT INTO documents (id, filename, metadata) VALUES (?, ?, ?::jsonb)")) {
            stmt.setObject(1, UUID.fromString(documentId));
            stmt.setString(2, filename);
            stmt.setString(3, toJson(metadata));
            stmt.executeUpdate();
            conn.commit();
        }
    }

    @Override
    public void insertChunk(String documentId, String documentName, int chunkIndex, String text,
                              Integer tokenCount, List<Double> embedding, Map<String, Object> metadata) throws SQLException {
        String embeddingLiteral = toVectorLiteral(embedding);
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, embedding, metadata) " +
                     "VALUES (?, ?, ?, ?, ?, ?::vector, ?::jsonb)")) {
            stmt.setObject(1, UUID.fromString(documentId));
            stmt.setString(2, documentName);
            stmt.setInt(3, chunkIndex);
            stmt.setString(4, text);
            if (tokenCount != null) {
                stmt.setInt(5, tokenCount);
            } else {
                stmt.setNull(5, java.sql.Types.INTEGER);
            }
            stmt.setString(6, embeddingLiteral);
            stmt.setString(7, toJson(metadata));
            stmt.executeUpdate();
            conn.commit();
        }
    }

    @Override
    public List<SearchResult> searchDense(List<Double> embedding, int topK, Map<String, Object> metadataFilter) throws SQLException {
        if (embedding == null || embedding.isEmpty()) {
            return List.of();
        }
        int dims = this.dimensions != null ? this.dimensions : embedding.size();
        String literal = toVectorLiteral(embedding);

        StringBuilder sql = new StringBuilder(String.format(
                "SELECT id, text, document_id, document_name, chunk_index, " +
                "1 - (embedding::halfvec(%1$d) <=> ?::halfvec(%1$d)) / 2 AS similarity_score " +
                "FROM chunks", dims));

        boolean hasFilter = metadataFilter != null && !metadataFilter.isEmpty();
        if (hasFilter) {
            sql.append(" WHERE metadata @> ?::jsonb");
        }
        sql.append(String.format(" ORDER BY embedding::halfvec(%1$d) <=> ?::halfvec(%1$d) LIMIT ?", dims));

        List<SearchResult> results = new ArrayList<>();
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(sql.toString())) {
            int i = 1;
            stmt.setString(i++, literal);
            if (hasFilter) {
                stmt.setString(i++, toJson(metadataFilter));
            }
            stmt.setString(i++, literal);
            stmt.setInt(i, topK);

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
        }
        return results;
    }

    @Override
    public List<DocumentSummary> listDocuments(int limit, int offset) throws SQLException {
        String sql = "SELECT d.id, d.filename, d.uploaded_at, d.metadata, COUNT(c.id) AS chunk_count " +
                "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id " +
                "GROUP BY d.id, d.filename, d.uploaded_at, d.metadata " +
                "ORDER BY d.uploaded_at DESC LIMIT ? OFFSET ?";

        List<DocumentSummary> results = new ArrayList<>();
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(sql)) {
            stmt.setInt(1, limit);
            stmt.setInt(2, offset);
            try (ResultSet rs = stmt.executeQuery()) {
                while (rs.next()) {
                    results.add(new DocumentSummary(
                            rs.getObject("id", UUID.class).toString(),
                            rs.getString("filename"),
                            rs.getObject("uploaded_at", OffsetDateTime.class),
                            fromJson(rs.getString("metadata")),
                            rs.getLong("chunk_count")
                    ));
                }
            }
        }
        return results;
    }

    @Override
    public boolean deleteDocument(String documentId) throws SQLException {
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement("DELETE FROM documents WHERE id = ?")) {
            stmt.setObject(1, UUID.fromString(documentId));
            int deleted = stmt.executeUpdate();
            conn.commit();
            return deleted > 0;
        }
    }

    @Override
    public Optional<String> getDocumentFilename(String documentId) throws SQLException {
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement("SELECT filename FROM documents WHERE id = ?")) {
            stmt.setObject(1, UUID.fromString(documentId));
            try (ResultSet rs = stmt.executeQuery()) {
                if (rs.next()) {
                    return Optional.of(rs.getString("filename"));
                }
                return Optional.empty();
            }
        }
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

    @SuppressWarnings("unchecked")
    private static Map<String, Object> fromJson(String json) throws SQLException {
        try {
            return json != null ? MAPPER.readValue(json, Map.class) : Map.of();
        } catch (Exception e) {
            throw new SQLException("Failed to parse metadata JSON", e);
        }
    }
}
