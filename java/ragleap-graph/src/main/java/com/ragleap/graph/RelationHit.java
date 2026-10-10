package com.ragleap.graph;

/** A typed relation between two entities. */
public record RelationHit(String subject, String relationType, String object, double weight) {
}
