package com.ragleap.rag.ingestion;

import com.ragleap.rag.chunker.Chunk;
import com.ragleap.rag.chunker.TextChunker;
import com.ragleap.rag.embedding.EmbeddingService;
import com.ragleap.rag.guardrails.GuardrailRunner;
import com.ragleap.rag.observability.ObservabilityHooks;
import com.ragleap.rag.parsers.DocumentParser;
import com.ragleap.rag.sanitization.ContentSanitizer;
import com.ragleap.rag.vectorstore.VectorBackend;

import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.UnaryOperator;
import java.util.logging.Logger;

/**
 * Turns files, text, images, audio and video into stored, embedded chunks. Java port of the ingest* methods of
 * ragleap-rag's RagLeap class (ingest, ingest_text, ingest_image, ingest_audio, ingest_video), built on the
 * modules already ported: parsers, sanitization, guardrails, chunker, embedding, vector backends, OCR, video
 * audio extraction and transcription. URL ingestion and batch ingestion are not ported yet.
 *
 * <p>The backend's schema must already be initialized (as in Python, ingestion does not do that).
 *
 * <p>Same pipeline as Python's ingest_text: sanitize (optional), warn on prompt-injection phrases (a warning, not
 * a block), run the input guardrails, chunk, create the document, embed and store each chunk in order (a chunk
 * whose embedding fails is skipped with a warning), delete the document and fail if nothing was stored, fire the
 * on_ingest hooks, return the id and the count. Errors that are ValueError in Python throw
 * IllegalArgumentException with the same wording.
 *
 * <p>Differences from Python: if storing fails part-way (a SQLException or any runtime error), the document
 * created by this call is deleted before the error propagates, where Python leaves the half-ingested document
 * behind; and the audio that video extraction produces is sent to the transcriber under a ".mp3" name that
 * matches its bytes, where Python sends it under the video's name (the stored document name is still the video's).
 */
public final class IngestionService {

    private static final Logger logger = Logger.getLogger(IngestionService.class.getName());

    private final VectorBackend backend;
    private final Function<String, List<Double>> embedder;
    private final TextChunker chunker;
    private final List<UnaryOperator<String>> inputGuardrails;
    private final List<Consumer<Map<String, Object>>> onIngest;
    private final ImageDescriber imageDescriber;

    /** Default chunking (512 tokens, 50 overlap), no guardrails, no hooks, no image captioning. */
    public IngestionService(VectorBackend backend, EmbeddingService embeddings) {
        this(backend, Objects.requireNonNull(embeddings, "embeddings")::embedText, new TextChunker(), null, null, null);
    }

    /**
     * @param embedder        returns the embedding for a text, or null if embedding failed (that chunk is skipped)
     * @param inputGuardrails applied in order to the text before chunking; may be null
     * @param onIngest        handlers called after a successful ingest; may be null
     * @param imageDescriber  used by ingestImage in "caption" mode; may be null
     */
    public IngestionService(VectorBackend backend, Function<String, List<Double>> embedder, TextChunker chunker,
                            List<UnaryOperator<String>> inputGuardrails, List<Consumer<Map<String, Object>>> onIngest,
                            ImageDescriber imageDescriber) {
        this.backend = Objects.requireNonNull(backend, "backend");
        this.embedder = Objects.requireNonNull(embedder, "embedder");
        this.chunker = Objects.requireNonNull(chunker, "chunker");
        this.inputGuardrails = inputGuardrails == null ? List.of() : List.copyOf(inputGuardrails);
        this.onIngest = onIngest == null ? List.of() : List.copyOf(onIngest);
        this.imageDescriber = imageDescriber;
    }

    // ------------------------------------------------------------------ text and files

    public IngestResult ingestText(String filename, String text) throws SQLException {
        return ingestText(filename, text, null, true, true);
    }

    public IngestResult ingestText(String filename, String text, Map<String, Object> metadata) throws SQLException {
        return ingestText(filename, text, metadata, true, true);
    }

    public IngestResult ingestText(String filename, String text, Map<String, Object> metadata,
                                   boolean sanitize, boolean warnOnInjectionRisk) throws SQLException {
        Objects.requireNonNull(filename, "filename");
        Objects.requireNonNull(text, "text");
        String current = text;
        if (sanitize) {
            current = ContentSanitizer.sanitizeText(current);
        }
        if (warnOnInjectionRisk) {
            List<String> risk = ContentSanitizer.detectInjectionRisk(current);
            if (!risk.isEmpty()) {
                logger.warning("Possible prompt-injection content in '" + filename + "': matched phrase(s) " + risk
                        + ". This is a heuristic signal, not a block - review the content if unexpected.");
            }
        }
        current = GuardrailRunner.runGuardrails(current, inputGuardrails);

        List<Chunk> chunks = chunker.chunkText(current);
        if (chunks.isEmpty()) {
            throw new IllegalArgumentException("No chunks produced from input text — is it empty?");
        }

        Map<String, Object> meta = metadata == null || metadata.isEmpty() ? Map.of() : metadata;
        String documentId = UUID.randomUUID().toString();
        backend.insertDocument(documentId, filename, meta);

        int stored = 0;
        try {
            for (Chunk chunk : chunks) {
                List<Double> embedding = embedder.apply(chunk.text());
                if (embedding == null) {
                    logger.warning("Skipping chunk " + chunk.chunkIndex() + " — embedding failed");
                    continue;
                }
                backend.insertChunk(documentId, filename, chunk.chunkIndex(), chunk.text(), chunk.tokenCount(),
                        embedding, meta);
                stored++;
            }
        } catch (SQLException | RuntimeException e) {
            try {
                backend.deleteDocument(documentId);
            } catch (SQLException | RuntimeException cleanupError) {
                e.addSuppressed(cleanupError);
            }
            throw e;
        }

        if (stored == 0) {
            backend.deleteDocument(documentId);
            throw new IllegalArgumentException("All " + chunks.size() + " chunk(s) failed to embed — nothing was stored.");
        }

        logger.info("Ingested '" + filename + "': " + stored + "/" + chunks.size() + " chunks stored");
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("document_id", documentId);
        event.put("filename", filename);
        event.put("chunks_stored", stored);
        event.put("chunks_attempted", chunks.size());
        ObservabilityHooks.fireEvent(event, onIngest, "on_ingest");
        return new IngestResult(documentId, stored);
    }

    /** Extracts the text of a file (any format DocumentParser supports, chosen by extension) and ingests it. */
    public IngestResult ingest(String filename, byte[] rawBytes) throws SQLException {
        return ingest(filename, rawBytes, null);
    }

    public IngestResult ingest(String filename, byte[] rawBytes, Map<String, Object> metadata) throws SQLException {
        String text = DocumentParser.extractText(filename, rawBytes);
        return ingestText(filename, text, metadata);
    }

    // ------------------------------------------------------------------ images, audio, video

    /** OCR mode, JPEG mime type, no metadata. */
    public IngestResult ingestImage(String filename, byte[] rawBytes) throws SQLException {
        return ingestImage(filename, rawBytes, "ocr", "image/jpeg", null);
    }

    /**
     * Mode "ocr" reads the text in the image with Tesseract; mode "caption" describes the image with the
     * configured {@link ImageDescriber}.
     */
    public IngestResult ingestImage(String filename, byte[] rawBytes, String mode, String mimeType,
                                    Map<String, Object> metadata) throws SQLException {
        String text = switch (mode) {
            case "ocr" -> OcrExtractor.extractText(rawBytes);
            case "caption" -> caption(rawBytes, mimeType);
            default -> throw new IllegalArgumentException("Unknown mode '" + mode + "'. Use 'ocr' or 'caption'.");
        };
        return ingestText(filename, text, metadata);
    }

    /**
     * Transcribes the audio and ingests the text. With no transcriber the default is OpenAI Whisper using the
     * OPENAI_API_KEY environment variable, as in Python.
     */
    public IngestResult ingestAudio(String filename, byte[] rawBytes, TranscriptionConfig transcriber,
                                    Map<String, Object> metadata) throws SQLException {
        return transcribeAndIngest(filename, filename, rawBytes, transcriber, metadata);
    }

    /** Extracts the audio track with ffmpeg, transcribes it and ingests the text. */
    public IngestResult ingestVideo(String filename, byte[] rawBytes, TranscriptionConfig transcriber,
                                    Map<String, Object> metadata) throws SQLException {
        byte[] audio = VideoAudioExtractor.extractAudio(rawBytes, filename);
        return transcribeAndIngest(filename, withMp3Extension(filename), audio, transcriber, metadata);
    }

    private IngestResult transcribeAndIngest(String documentName, String audioName, byte[] audio,
                                             TranscriptionConfig transcriber, Map<String, Object> metadata)
            throws SQLException {
        TranscriptionConfig config = transcriber != null
                ? transcriber : new TranscriptionConfig("whisper", null, null, null, null, null);
        String text = new TranscriptionService(config).transcribe(audioName, audio);
        return ingestText(documentName, text, metadata);
    }

    private String caption(byte[] imageBytes, String mimeType) {
        if (imageDescriber == null) {
            throw new IllegalStateException("mode 'caption' needs an ImageDescriber, for example "
                    + "new IngestionService(backend, embedder, chunker, null, null, generationService::describeImage).");
        }
        try {
            return imageDescriber.describe(imageBytes, mimeType);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Image captioning was interrupted", e);
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("Image captioning failed: " + e.getMessage(), e);
        }
    }

    static String withMp3Extension(String filename) {
        int dot = filename.lastIndexOf('.');
        return (dot > 0 ? filename.substring(0, dot) : filename) + ".mp3";
    }
}
