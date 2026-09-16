package com.ragleap.rag.memory;

import com.ragleap.rag.db.ConnectionPool;
import com.ragleap.rag.schema.SchemaManager;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Real integration test against the same live throwaway database used
 * by ConnectionPoolTest/SchemaManagerTest (ragleap_java_test) - not
 * mocked. Each test uses its own unique session_id to stay isolated
 * regardless of method execution order.
 */
class ConversationMemoryTest {

    private static final String DATABASE_URL = System.getenv().getOrDefault(
            "RAGLEAP_JAVA_TEST_DATABASE_URL",
            "postgresql://ragleap:ragleap@localhost:5433/ragleap_java_test"
    );

    private static ConnectionPool pool;

    @BeforeAll
    static void setUpPool() throws SQLException {
        pool = new ConnectionPool(DATABASE_URL, 1, 5);
        SchemaManager.initMemorySchema(pool);
    }

    @AfterAll
    static void tearDownPool() throws SQLException {
        try (Connection conn = pool.getConnection();
             PreparedStatement stmt = conn.prepareStatement(
                     "DELETE FROM conversations WHERE session_id LIKE 'test-memory-%'")) {
            stmt.executeUpdate();
            conn.commit();
        }
        pool.close();
    }

    @Test
    void addMessageAndGetHistoryReturnsMessagesInChronologicalOrder() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);
        String sessionId = "test-memory-chronological";

        memory.addMessage(sessionId, "user", "What channels does RagLeap support?");
        memory.addMessage(sessionId, "assistant", "WhatsApp, Telegram, and voice calls.");
        memory.addMessage(sessionId, "user", "What about email?");

        List<ConversationMessage> history = memory.getHistory(sessionId);

        assertEquals(3, history.size());
        assertEquals("user", history.get(0).role());
        assertEquals("What channels does RagLeap support?", history.get(0).content());
        assertEquals("assistant", history.get(1).role());
        assertEquals("user", history.get(2).role());
        assertEquals("What about email?", history.get(2).content());
        assertNotNull(history.get(0).createdAt());
    }

    @Test
    void getHistoryRespectsExplicitLimitOverridingDefault() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);
        String sessionId = "test-memory-limit";

        for (int i = 1; i <= 5; i++) {
            memory.addMessage(sessionId, "user", "message " + i);
        }

        List<ConversationMessage> limited = memory.getHistory(sessionId, 2);

        assertEquals(2, limited.size());
        // Most recent 2, oldest-first within that window
        assertEquals("message 4", limited.get(0).content());
        assertEquals("message 5", limited.get(1).content());
    }

    @Test
    void constructorWithCustomMaxHistoryMessagesAppliesAsDefaultLimit() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool, 2);
        String sessionId = "test-memory-custom-default";

        for (int i = 1; i <= 5; i++) {
            memory.addMessage(sessionId, "user", "msg " + i);
        }

        List<ConversationMessage> history = memory.getHistory(sessionId);

        assertEquals(2, history.size());
        assertEquals("msg 4", history.get(0).content());
        assertEquals("msg 5", history.get(1).content());
    }

    @Test
    void getHistoryReturnsEmptyListForUnknownSession() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);

        List<ConversationMessage> history = memory.getHistory("test-memory-never-existed");

        assertTrue(history.isEmpty());
    }

    @Test
    void clearSessionDeletesMessagesViaCascade() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);
        String sessionId = "test-memory-clear";

        memory.addMessage(sessionId, "user", "hello");
        assertEquals(1, memory.getHistory(sessionId).size());

        memory.clearSession(sessionId);

        assertTrue(memory.getHistory(sessionId).isEmpty());
    }

    @Test
    void buildHistoryPromptReturnsEmptyStringWhenNoHistory() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);

        String prompt = memory.buildHistoryPrompt("test-memory-no-history-ever");

        assertEquals("", prompt);
    }

    @Test
    void buildHistoryPromptFormatsRoleCapitalizedAndJoinsWithNewlines() throws SQLException {
        ConversationMemory memory = new ConversationMemory(pool);
        String sessionId = "test-memory-prompt-format";

        memory.addMessage(sessionId, "user", "hi there");
        memory.addMessage(sessionId, "assistant", "hello!");

        String prompt = memory.buildHistoryPrompt(sessionId);

        assertEquals("Previous conversation:\nUser: hi there\nAssistant: hello!\n\n", prompt);
    }
}
