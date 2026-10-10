package com.ragleap.graph;

import java.util.List;
import java.util.Map;

/** Runs one Cypher statement in its own auto-commit transaction and returns its rows. */
public interface CypherRunner extends AutoCloseable {
    List<Map<String, Object>> run(String cypher, Map<String, Object> params);

    @Override
    default void close() {
    }
}
