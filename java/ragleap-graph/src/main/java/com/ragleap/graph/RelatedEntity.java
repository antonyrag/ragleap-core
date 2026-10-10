package com.ragleap.graph;

/** An entity found by graph traversal, with the type of the first relationship on the path and its depth. */
public record RelatedEntity(String entityId, String entityName, String relationship, int depth) {
}
