package com.ragleap.rag.parsers;

/**
 * Thrown when an archive has too many members or too much uncompressed data. The counterpart of the
 * Python package's ValueError for the same case, so it is an IllegalArgumentException.
 */
public final class ZipLimitException extends IllegalArgumentException {

    public ZipLimitException(String message) {
        super(message);
    }
}
