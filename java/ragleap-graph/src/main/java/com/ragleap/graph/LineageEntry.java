package com.ragleap.graph;

/**
 * One document's contribution to an edge. relationType is CO_OCCURS_WITH or RELATES_AS;
 * relationName is only set for RELATES_AS.
 */
public record LineageEntry(String documentId, String relationType, String relationName, Double weight) {
}
