package com.ragleap.graph;

/** Outcome of an upsertDocument call. error is null on success. */
public record UpsertSummary(boolean success, String documentId, int entitiesIndexed,
                            int relationshipsIndexed, int relationsIndexed, String error) {
}
