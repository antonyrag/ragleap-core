package com.ragleap.graph;

/** Any failure talking to Neo4j (connection, HTTP, or a Neo4j error). */
public class GraphException extends RuntimeException {
    public GraphException(String message) {
        super(message);
    }

    public GraphException(String message, Throwable cause) {
        super(message, cause);
    }
}
