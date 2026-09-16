package com.ragleap.rag.memory;

import com.ragleap.rag.db.ConnectionPool;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.logging.Logger;

/**
 * Stores and retrieves per-session conversation history. Java port of
 * ragleap-rag's memory.py - ConversationMemory. Session-scoped,
 * Postgres-backed via ConnectionPool; opt-in per call, matching the
 * Python source's documented usage (pass a session_id to get
 * multi-turn context, omit it for stateless behavior).
 *
 * Relies on the conversations/conversation_messages tables created by
 * SchemaManager.initMemorySchema() - this class does not create
 * schema itself, same division of responsibility as the Python
 * source (schema.py owns DDL, memory.py owns reads/writes).
 */
public class ConversationMemory {

    private static final Logger logger = Logger.getLogger(ConversationMemory.class.getName());
    public static final int DEFAULT_MAX_HISTORY_MESSAGES = 10;

    private final ConnectionPool pool;
    private final int maxHistoryMessages;

    public ConversationMemory(ConnectionPool pool) {
        this(pool, DEFAULT_MAX_HISTORY_MESSAGES);
    }

    public ConversationMemory(ConnectionPool pool, int maxHistoryMessages) {
        this.pool = pool;
        this.maxHistoryMessages = maxHistoryMessages;
    }

    private void ensureSession(Connection conn, String sessionId) throws SQLException {
        try (PreparedStatement stmt = conn.prepareStatement(
                "INSERT INTO conversations (session_id) VALUES (?) " +
                "ON CONFLICT (session_id) DO UPDATE SET updated_at = now()")) {
            stmt.setString(1, sessionId);
            stmt.executeUpdate();
        }
    }

    /** Store a single message (role: "user" or "assistant" - enforced by the table's CHECK constraint). */
    public void addMessage(String sessionId, String role, String content) throws SQLException {
        try (Connection conn = pool.getConnection()) {
            ensureSession(conn, sessionId);
            try (PreparedStatement stmt = conn.prepareStatement(
                    "INSERT INTO conversation_messages (session_id, role, content) VALUES (?, ?, ?)")) {
                stmt.setString(1, sessionId);
                stmt.setString(2, role);
                stmt.setString(3, content);
                stmt.executeUpdate();
            }
            conn.commit();
        }
    }

    /** Recent messages for a session, oldest first, using the configured default limit. */
    public List<ConversationMessage> getHistory(String sessionId) throws SQLException {
        return getHistory(sessionId, null);
    }

    /**
     * Recent messages for a session, oldest first. If limit is null,
     * uses the configured maxHistoryMessages - matches the Python
     * source's limit: int = None default.
     */
    public List<ConversationMessage> getHistory(String sessionId, Integer limit) throws SQLException {
        int effectiveLimit = limit != null ? limit : maxHistoryMessages;
        List<ConversationMessage> messages = new ArrayList<>();
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "SELECT role, content, created_at FROM conversation_messages " +
                     "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?")) {
            stmt.setString(1, sessionId);
            stmt.setInt(2, effectiveLimit);
            try (ResultSet rs = stmt.executeQuery()) {
                while (rs.next()) {
                    messages.add(new ConversationMessage(
                            rs.getString("role"),
                            rs.getString("content"),
                            rs.getObject("created_at", OffsetDateTime.class)));
                }
            }
        }
        // Query orders DESC (most recent first, so LIMIT keeps the most
        // recent N) then reverse in memory to return oldest-first -
        // matches the Python source's reversed(rows) exactly.
        Collections.reverse(messages);
        return messages;
    }

    /** Delete a session and all its messages (ON DELETE CASCADE handles the messages). */
    public void clearSession(String sessionId) throws SQLException {
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement("DELETE FROM conversations WHERE session_id = ?")) {
            stmt.setString(1, sessionId);
            stmt.executeUpdate();
            conn.commit();
        }
        logger.info(() -> "Cleared session '" + sessionId + "'");
    }

    /** Prior turns formatted for injection into a prompt. Empty string if no history. */
    public String buildHistoryPrompt(String sessionId) throws SQLException {
        List<ConversationMessage> history = getHistory(sessionId);
        if (history.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("Previous conversation:\n");
        for (int i = 0; i < history.size(); i++) {
            ConversationMessage m = history.get(i);
            String role = m.role();
            String capitalizedRole = role.isEmpty() ? role
                    : Character.toUpperCase(role.charAt(0)) + role.substring(1).toLowerCase();
            sb.append(capitalizedRole).append(": ").append(m.content());
            if (i < history.size() - 1) {
                sb.append("\n");
            }
        }
        sb.append("\n\n");
        return sb.toString();
    }
}
