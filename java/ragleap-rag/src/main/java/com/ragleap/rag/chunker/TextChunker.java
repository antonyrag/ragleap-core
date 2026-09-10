package com.ragleap.rag.chunker;

import com.knuddels.jtokkit.Encodings;
import com.knuddels.jtokkit.api.Encoding;
import com.knuddels.jtokkit.api.EncodingRegistry;
import com.knuddels.jtokkit.api.EncodingType;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Splits documents into overlapping chunks for embedding and retrieval.
 * Java port of ragleap-rag's chunker.py — TextChunker.
 */
public class TextChunker {

    private static final Logger logger = Logger.getLogger(TextChunker.class.getName());

    public static final int DEFAULT_CHUNK_SIZE = 512;
    public static final int DEFAULT_CHUNK_OVERLAP = 50;

    // Mirrors the Python module's _encoding_cache: resolve cl100k_base once,
    // reuse it. jtokkit's registry/encoding objects are safe to share.
    private static final EncodingRegistry REGISTRY = Encodings.newDefaultEncodingRegistry();
    private static volatile Encoding cl100kEncoding;

    private final int chunkSize;
    private final int chunkOverlap;

    public TextChunker() {
        this(DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP);
    }

    public TextChunker(int chunkSize, int chunkOverlap) {
        this.chunkSize = chunkSize;
        this.chunkOverlap = chunkOverlap;

        if (this.chunkOverlap >= this.chunkSize) {
            throw new IllegalArgumentException("Chunk overlap must be less than chunk size");
        }

        logger.info(() -> String.format(
                "Initialized TextChunker: size=%d, overlap=%d", this.chunkSize, this.chunkOverlap));
    }

    public int getChunkSize() {
        return chunkSize;
    }

    public int getChunkOverlap() {
        return chunkOverlap;
    }

    /** Simple whitespace tokenization — mirrors Python's str.split(). */
    private List<String> tokenize(String text) {
        List<String> tokens = new ArrayList<>();
        for (String t : text.trim().split("\\s+")) {
            if (!t.isEmpty()) {
                tokens.add(t);
            }
        }
        return tokens;
    }

    /**
     * Split text into overlapping chunks with metadata.
     * Slides a window of chunkSize tokens with step (chunkSize - chunkOverlap),
     * breaking once a window reaches the end of the token list — matching
     * chunker.py's for/break boundary exactly (not after, to keep chunk-count parity).
     */
    public List<Chunk> chunkText(String text) {
        if (text == null || text.strip().isEmpty()) {
            logger.warning("Empty text provided for chunking");
            return List.of();
        }

        List<String> tokens = tokenize(text);
        if (tokens.isEmpty()) {
            logger.warning("No tokens extracted from text");
            return List.of();
        }

        List<Chunk> chunks = new ArrayList<>();
        int step = chunkSize - chunkOverlap;
        int chunkIndex = 0;

        for (int start = 0; start < tokens.size(); start += step) {
            int end = Math.min(start + chunkSize, tokens.size());
            String chunkTextContent = String.join(" ", tokens.subList(start, end));

            TokenCount tc = realTokenCount(chunkTextContent);
            chunks.add(new Chunk(chunkTextContent, chunkIndex, tc.count(), tc.isExact()));
            chunkIndex++;

            if (end == tokens.size()) {
                break;
            }
        }

        logger.info(() -> String.format("Chunked text into %d chunks", chunks.size()));
        return chunks;
    }

    private record TokenCount(int count, boolean isExact) {}

    /**
     * Real LLM token count via jtokkit's cl100k_base encoding — the Java
     * equivalent of tiktoken. Falls back to a whitespace word count with
     * isExact=false only if the encoding genuinely can't be obtained —
     * the fallback is never reported as exact.
     */
    private TokenCount realTokenCount(String text) {
        try {
            Encoding encoding = cl100kEncoding;
            if (encoding == null) {
                synchronized (TextChunker.class) {
                    encoding = cl100kEncoding;
                    if (encoding == null) {
                        encoding = REGISTRY.getEncoding(EncodingType.CL100K_BASE);
                        cl100kEncoding = encoding;
                    }
                }
            }
            return new TokenCount(encoding.countTokens(text), true);
        } catch (Exception e) {
            logger.warning("jtokkit encoding unavailable (" + e.getMessage()
                    + "); falling back to word count");
            int wordCount = text.isBlank() ? 0 : text.trim().split("\\s+").length;
            return new TokenCount(wordCount, false);
        }
    }

    public static TextChunker createChunker() {
        return new TextChunker();
    }

    public static TextChunker createChunker(int chunkSize, int chunkOverlap) {
        return new TextChunker(chunkSize, chunkOverlap);
    }
}
