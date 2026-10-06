package com.ragleap.rag.ingestion;

/**
 * A custom transcription function for provider "custom": receives the filename and the audio bytes and returns
 * the transcript. Java counterpart of the Python transcribe_fn callable. Any provider can be plugged in this way.
 */
@FunctionalInterface
public interface TranscribeFunction {

    String transcribe(String filename, byte[] audioBytes);
}
