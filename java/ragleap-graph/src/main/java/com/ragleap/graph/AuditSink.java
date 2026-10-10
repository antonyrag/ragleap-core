package com.ragleap.graph;

import java.util.Map;

/** Receives audit events. Implementations must not let a failure break the audited operation. */
public interface AuditSink {
    AuditSink NOOP = (userId, namespace, action, documentId, entityCount, detail) -> { };

    void log(String userId, String namespace, String action, String documentId, Integer entityCount,
             Map<String, Object> detail);

    default void close() {
    }
}
