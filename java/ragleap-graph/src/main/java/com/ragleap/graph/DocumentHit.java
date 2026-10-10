package com.ragleap.graph;

import java.util.List;

/** One document found through its entities, ranked by matched entities and summed edge weight. */
public record DocumentHit(String documentId, String documentName, int matchedEntities, double graphScore,
                          List<String> matchedEntityNames) {
}
