package com.ragleap.rag.ingestion;

/**
 * A transcription request failed at the HTTP level: a non-2xx answer (the status code is available) or a
 * transport error (status code -1). The message never contains the API key.
 */
public class TranscriptionApiException extends RuntimeException {

    private final int statusCode;

    public TranscriptionApiException(String message, int statusCode, Throwable cause) {
        super(message, cause);
        this.statusCode = statusCode;
    }

    /** The HTTP status code, or -1 if no response was received. */
    public int getStatusCode() {
        return statusCode;
    }
}
