package com.ragleap.graph;

/** A Neo4j transient error (Neo.TransientError.*), for example a deadlock. Safe to retry. */
public class GraphTransientException extends GraphException {
    public GraphTransientException(String message) {
        super(message);
    }
}
