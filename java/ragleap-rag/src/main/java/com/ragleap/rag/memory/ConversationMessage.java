package com.ragleap.rag.memory;

import java.time.OffsetDateTime;

/**
 * One stored message. Java equivalent of the
 * {"role", "content", "created_at"} dicts returned by
 * ConversationMemory.get_history() in memory.py.
 */
public record ConversationMessage(String role, String content, OffsetDateTime createdAt) {
}
