package com.ragleap.rag.ingestion;

/** The outcome of an ingest call: the new document's id and how many chunks were stored. */
public record IngestResult(String documentId, int chunksStored) {
}
