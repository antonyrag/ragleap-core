package com.ragleap.rag.vectorstore;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Types;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.locks.ReentrantLock;

/**
 * FAISS-backed vector storage for ragleap-rag (Java port).
 *
 * <p>Local, in-process, no API key, no external service - mirrors the
 * Python {@code FAISSBackend}'s purpose exactly. Honest limitations,
 * stated upfront (matching the Python source's own docstring standard):
 * <ul>
 *   <li>No native full-text search - {@link #supportsSparse()} is
 *   {@code false}, and callers relying on hybrid search gracefully
 *   degrade to dense-only via {@link VectorBackend}'s default methods.</li>
 *   <li>Metadata filtering is a post-filter: candidates are over-fetched
 *   from the in-memory index, then filtered by metadata from SQLite -
 *   less efficient than pgvector's indexed JSONB containment at scale.</li>
 *   <li>Without a persist directory, everything is in-memory and lost
 *   when the process exits - by design, not a bug.</li>
 * </ul>
 *
 * <p>Deliberate deviations from the Python source, documented rather than
 * discovered later:
 * <ul>
 *   <li><b>No native FAISS wrapping.</b> There is no practical way to call
 *   the native FAISS C++ library from pure Java without JNI. The Python
 *   backend only ever uses FAISS's simplest exact mode
 *   ({@code IndexIDMap(IndexFlatIP(dim))}) - an exact brute-force
 *   inner-product search over L2-normalized vectors, mathematically
 *   equivalent to cosine similarity. This class reimplements that exact
 *   algorithm directly in Java ({@code Map<Long, float[]>} plus a linear
 *   dot-product scan) rather than wrapping the native library. This is a
 *   faithful functional port, not a byte-compatible one.</li>
 *   <li><b>Custom persistence format.</b> FAISS's own binary index-file
 *   format is unreadable from pure Java without wrapping the native
 *   library, so a simple custom binary format is used instead - see
 *   {@link #saveIndexIfPersistent()}.</li>
 *   <li><b>{@link AutoCloseable}.</b> Java has no implicit destructor;
 *   the Python source has no explicit teardown at all. This class closes
 *   its JDBC connection cleanly on {@link #close()}, a reasonable
 *   Java-specific addition.</li>
 * </ul>
 */
public class FaissBackend implements VectorBackend, AutoCloseable {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final Path indexPath;
    private final Connection conn;
    private final ReentrantLock lock = new ReentrantLock();
    private final Map<Long, float[]> vectors = new HashMap<>();
    private Integer dimensions;

    public FaissBackend() throws SQLException {
        this(null);
    }

    public FaissBackend(String persistDirectory) throws SQLException {
        String jdbcUrl;
        if (persistDirectory != null) {
            File dir = new File(persistDirectory);
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IllegalStateException("Could not create persist directory: " + persistDirectory);
            }
            File sqliteFile = new File(dir, "faiss_meta.sqlite3");
            this.indexPath = Paths.get(dir.getAbsolutePath(), "faiss.index");
            jdbcUrl = "jdbc:sqlite:" + sqliteFile.getAbsolutePath();
        } else {
            this.indexPath = null;
            jdbcUrl = "jdbc:sqlite::memory:";
        }

        this.conn = DriverManager.getConnection(jdbcUrl);
        try (Statement st = conn.createStatement()) {
            st.execute("CREATE TABLE IF NOT EXISTS documents (" +
                    "id TEXT PRIMARY KEY, filename TEXT NOT NULL, metadata TEXT NOT NULL, uploaded_at TEXT NOT NULL)");
            st.execute("CREATE TABLE IF NOT EXISTS chunks (" +
                    "vid INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL, " +
                    "document_name TEXT NOT NULL, chunk_index INTEGER NOT NULL, " +
                    "text TEXT NOT NULL, token_count INTEGER, metadata TEXT NOT NULL)");
        }
    }

    @Override
    public void initSchema(int dimensions) throws SQLException {
        lock.lock();
        try {
            this.dimensions = dimensions;
            vectors.clear();
            if (indexPath != null && Files.exists(indexPath)) {
                loadIndex();
            }
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void insertDocument(String documentId, String filename, Map<String, Object> metadata) throws SQLException {
        String metaJson = toJson(metadata);
        String uploadedAt = OffsetDateTime.now(ZoneOffset.UTC).toString();
        lock.lock();
        try {
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO documents (id, filename, metadata, uploaded_at) VALUES (?, ?, ?, ?)")) {
                ps.setString(1, documentId);
                ps.setString(2, filename);
                ps.setString(3, metaJson);
                ps.setString(4, uploadedAt);
                ps.executeUpdate();
            }
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void insertChunk(String documentId, String documentName, int chunkIndex, String text,
                             Integer tokenCount, List<Double> embedding, Map<String, Object> metadata) throws SQLException {
        String metaJson = toJson(metadata);
        lock.lock();
        try {
            long vid;
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO chunks (document_id, document_name, chunk_index, text, token_count, metadata) VALUES (?, ?, ?, ?, ?, ?)")) {
                ps.setString(1, documentId);
                ps.setString(2, documentName);
                ps.setInt(3, chunkIndex);
                ps.setString(4, text);
                if (tokenCount != null) {
                    ps.setInt(5, tokenCount);
                } else {
                    ps.setNull(5, Types.INTEGER);
                }
                ps.setString(6, metaJson);
                ps.executeUpdate();
                try (ResultSet keys = ps.getGeneratedKeys()) {
                    keys.next();
                    vid = keys.getLong(1);
                }
            }

            vectors.put(vid, normalize(embedding));
            saveIndexIfPersistent();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public List<SearchResult> searchDense(List<Double> embedding, int topK, Map<String, Object> metadataFilter) throws SQLException {
        if (embedding == null || embedding.isEmpty()) {
            return List.of();
        }
        if (dimensions != null && embedding.size() != dimensions) {
            return List.of();
        }

        float[] query = normalize(embedding);
        int fetchK = metadataFilter != null && !metadataFilter.isEmpty() ? topK * 5 : topK;

        List<Map.Entry<Long, Double>> scored;
        lock.lock();
        try {
            if (vectors.isEmpty()) {
                return List.of();
            }
            fetchK = Math.min(fetchK, vectors.size());
            scored = new ArrayList<>(vectors.size());
            for (Map.Entry<Long, float[]> e : vectors.entrySet()) {
                scored.add(Map.entry(e.getKey(), dot(query, e.getValue())));
            }
        } finally {
            lock.unlock();
        }

        scored.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));

        List<SearchResult> results = new ArrayList<>();
        for (int i = 0; i < Math.min(fetchK, scored.size()) && results.size() < topK; i++) {
            long vid = scored.get(i).getKey();
            double score = scored.get(i).getValue();

            String documentId, documentName, text, metaJson;
            int chunkIndex;
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT document_id, document_name, chunk_index, text, metadata FROM chunks WHERE vid = ?")) {
                ps.setLong(1, vid);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) continue;
                    documentId = rs.getString(1);
                    documentName = rs.getString(2);
                    chunkIndex = rs.getInt(3);
                    text = rs.getString(4);
                    metaJson = rs.getString(5);
                }
            }

            if (!metadataMatches(metaJson, metadataFilter)) continue;

            results.add(new SearchResult(String.valueOf(vid), text, round4(score), documentId, documentName, chunkIndex));
        }
        return results;
    }

    @Override
    public boolean supportsSparse() {
        return false;
    }

    @Override
    public List<DocumentSummary> listDocuments(int limit, int offset) throws SQLException {
        List<DocumentSummary> out = new ArrayList<>();
        String sql = "SELECT d.id, d.filename, d.uploaded_at, d.metadata, COUNT(c.vid) AS chunk_count " +
                "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id " +
                "GROUP BY d.id ORDER BY d.uploaded_at DESC LIMIT ? OFFSET ?";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setInt(1, limit);
            ps.setInt(2, offset);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(new DocumentSummary(
                            rs.getString(1),
                            rs.getString(2),
                            OffsetDateTime.parse(rs.getString(3)),
                            fromJson(rs.getString(4)),
                            rs.getLong(5)
                    ));
                }
            }
        }
        return out;
    }

    @Override
    public boolean deleteDocument(String documentId) throws SQLException {
        lock.lock();
        try {
            List<Long> vids = new ArrayList<>();
            try (PreparedStatement ps = conn.prepareStatement("SELECT vid FROM chunks WHERE document_id = ?")) {
                ps.setString(1, documentId);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) vids.add(rs.getLong(1));
                }
            }
            for (Long vid : vids) vectors.remove(vid);

            int deletedCount;
            try (PreparedStatement ps = conn.prepareStatement("DELETE FROM documents WHERE id = ?")) {
                ps.setString(1, documentId);
                deletedCount = ps.executeUpdate();
            }
            try (PreparedStatement ps = conn.prepareStatement("DELETE FROM chunks WHERE document_id = ?")) {
                ps.setString(1, documentId);
                ps.executeUpdate();
            }

            saveIndexIfPersistent();
            return deletedCount > 0;
        } finally {
            lock.unlock();
        }
    }

    @Override
    public Optional<String> getDocumentFilename(String documentId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT filename FROM documents WHERE id = ?")) {
            ps.setString(1, documentId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? Optional.of(rs.getString(1)) : Optional.empty();
            }
        }
    }

    @Override
    public void close() throws SQLException {
        conn.close();
    }

    // --- internals ---

    private float[] normalize(List<Double> embedding) {
        float[] v = new float[embedding.size()];
        double normSq = 0;
        for (int i = 0; i < embedding.size(); i++) {
            v[i] = embedding.get(i).floatValue();
            normSq += (double) v[i] * v[i];
        }
        double norm = Math.sqrt(normSq);
        if (norm > 0) {
            for (int i = 0; i < v.length; i++) {
                v[i] = (float) (v[i] / norm);
            }
        }
        return v;
    }

    private static double dot(float[] a, float[] b) {
        double sum = 0;
        int n = Math.min(a.length, b.length);
        for (int i = 0; i < n; i++) sum += (double) a[i] * b[i];
        return sum;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private boolean metadataMatches(String storedJson, Map<String, Object> filter) {
        if (filter == null || filter.isEmpty()) return true;
        Map<String, Object> stored = fromJson(storedJson);
        for (Map.Entry<String, Object> e : filter.entrySet()) {
            if (!Objects.equals(stored.get(e.getKey()), e.getValue())) return false;
        }
        return true;
    }

    private String toJson(Map<String, Object> map) {
        try {
            return MAPPER.writeValueAsString(map != null ? map : Map.of());
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize metadata", e);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> fromJson(String json) {
        try {
            return MAPPER.readValue(json, Map.class);
        } catch (Exception e) {
            throw new RuntimeException("Failed to parse metadata", e);
        }
    }

    /**
     * Custom binary persistence format - NOT FAISS's own index-file
     * format, which cannot be read or written from pure Java without
     * wrapping the native library. Layout: {@code int32 dimensions},
     * then repeated {@code int64 vid, float32[dimensions] vector} for
     * each entry. An intentional, documented deviation - a faithful
     * functional port, not a byte-compatible one.
     */
    private void saveIndexIfPersistent() {
        if (indexPath == null) return;
        try (DataOutputStream out = new DataOutputStream(
                new BufferedOutputStream(new FileOutputStream(indexPath.toFile())))) {
            out.writeInt(dimensions != null ? dimensions : 0);
            for (Map.Entry<Long, float[]> e : vectors.entrySet()) {
                out.writeLong(e.getKey());
                for (float f : e.getValue()) {
                    out.writeFloat(f);
                }
            }
        } catch (IOException e) {
            throw new RuntimeException("Failed to persist FAISS index to " + indexPath, e);
        }
    }

    private void loadIndex() {
        try (DataInputStream in = new DataInputStream(
                new BufferedInputStream(new FileInputStream(indexPath.toFile())))) {
            int dim = in.readInt();
            if (dim > 0) this.dimensions = dim;
            vectors.clear();
            while (true) {
                long vid;
                try {
                    vid = in.readLong();
                } catch (EOFException eof) {
                    break;
                }
                float[] v = new float[dim];
                for (int i = 0; i < dim; i++) v[i] = in.readFloat();
                vectors.put(vid, v);
            }
        } catch (IOException e) {
            throw new RuntimeException("Failed to load FAISS index from " + indexPath, e);
        }
    }
}
