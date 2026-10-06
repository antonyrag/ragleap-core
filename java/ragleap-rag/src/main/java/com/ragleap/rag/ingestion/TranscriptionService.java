package com.ragleap.rag.ingestion;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;

/**
 * Transcribes audio to text with the configured provider. Java port of ragleap-rag's transcription.py
 * (TranscriptionService), using java.net.http directly instead of the OpenAI and requests libraries.
 *
 * <p>NOT live-verified: no paid account was available. The request shapes follow the providers' public API
 * documentation (OpenAI: multipart POST to /audio/transcriptions with model, file, language, prompt; Deepgram:
 * raw audio POST to /v1/listen with model and smart_format query parameters) and are checked against a local stub
 * server, the same label Milvus and Pinecone carry.
 *
 * <p>Differences from Python: no automatic retries (the OpenAI SDK retries twice by default), redirects are not
 * followed (so the API key cannot be forwarded to another host), the multipart file part is sent as
 * application/octet-stream, and the API key is redacted from error messages. Timeouts match Python: 600 seconds
 * for Whisper (the SDK default) and 120 seconds for Deepgram.
 */
public final class TranscriptionService {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Duration WHISPER_TIMEOUT = Duration.ofSeconds(600);
    private static final Duration DEEPGRAM_TIMEOUT = Duration.ofSeconds(120);

    private final TranscriptionConfig config;
    private final HttpClient http;

    public TranscriptionService(TranscriptionConfig config) {
        this(config, HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(30))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build());
    }

    TranscriptionService(TranscriptionConfig config, HttpClient http) {
        this.config = Objects.requireNonNull(config, "config");
        this.http = Objects.requireNonNull(http, "http");
    }

    /** Transcribes the audio and returns the text. */
    public String transcribe(String filename, byte[] audioBytes) {
        Objects.requireNonNull(filename, "filename");
        Objects.requireNonNull(audioBytes, "audioBytes");
        return switch (config.provider()) {
            case "whisper" -> transcribeWhisper(filename, audioBytes);
            case "deepgram" -> transcribeDeepgram(audioBytes);
            default -> config.transcribeFn().transcribe(filename, audioBytes);
        };
    }

    // ------------------------------------------------------------------ Whisper

    private String transcribeWhisper(String filename, byte[] audio) {
        String boundary = "----RagLeapBoundary" + UUID.randomUUID().toString().replace("-", "");
        ByteArrayOutputStream body = new ByteArrayOutputStream(audio.length + 1024);
        writeField(body, boundary, "model", config.model());
        if (notEmpty(config.language())) {
            writeField(body, boundary, "language", config.language());
        }
        if (notEmpty(config.prompt())) {
            writeField(body, boundary, "prompt", config.prompt());
        }
        writeText(body, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\""
                + escapeFilename(filename) + "\"\r\nContent-Type: application/octet-stream\r\n\r\n");
        body.writeBytes(audio);
        writeText(body, "\r\n--" + boundary + "--\r\n");

        HttpRequest request = HttpRequest.newBuilder(URI.create(config.effectiveBaseUrl() + "/audio/transcriptions"))
                .timeout(WHISPER_TIMEOUT)
                .header("Authorization", "Bearer " + config.apiKey())
                .header("Content-Type", "multipart/form-data; boundary=" + boundary)
                .POST(HttpRequest.BodyPublishers.ofByteArray(body.toByteArray()))
                .build();
        String responseBody = send(request, "Whisper");

        JsonNode json = readJson(responseBody, "Whisper");
        JsonNode textNode = json.path("text");
        if (!textNode.isTextual()) {
            throw shape("Whisper", responseBody);
        }
        String text = textNode.asText();
        if (isBlank(text)) {
            throw new IllegalArgumentException("Whisper returned an empty transcription — check the audio has audible speech.");
        }
        return text;
    }

    // ------------------------------------------------------------------ Deepgram

    private String transcribeDeepgram(byte[] audio) {
        StringBuilder query = new StringBuilder("model=").append(urlEncode(config.model())).append("&smart_format=true");
        if (notEmpty(config.language())) {
            query.append("&language=").append(urlEncode(config.language()));
        }
        HttpRequest request = HttpRequest.newBuilder(URI.create(config.effectiveBaseUrl() + "/v1/listen?" + query))
                .timeout(DEEPGRAM_TIMEOUT)
                .header("Authorization", "Token " + config.apiKey())
                .header("Content-Type", "audio/*")
                .POST(HttpRequest.BodyPublishers.ofByteArray(audio))
                .build();
        String responseBody = send(request, "Deepgram");

        JsonNode json = readJson(responseBody, "Deepgram");
        JsonNode transcript = json.path("results").path("channels").path(0).path("alternatives").path(0).path("transcript");
        if (transcript.isMissingNode()) {
            throw shape("Deepgram", responseBody);
        }
        String text = transcript.isNull() ? null : transcript.asText();
        if (text == null || isBlank(text)) {
            throw new IllegalArgumentException("Deepgram returned an empty transcription — check the audio has audible speech.");
        }
        return text;
    }

    // ------------------------------------------------------------------ helpers

    private String send(HttpRequest request, String providerName) {
        HttpResponse<String> response;
        try {
            response = http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new TranscriptionApiException(providerName + " request failed: " + e.getClass().getSimpleName()
                    + ": " + redact(e.getMessage()), -1, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new TranscriptionApiException(providerName + " request was interrupted", -1, e);
        }
        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            throw new TranscriptionApiException(providerName + " request failed: HTTP " + status + ": "
                    + clip(redact(response.body()), 500), status, null);
        }
        return response.body();
    }

    private static JsonNode readJson(String body, String what) {
        JsonNode node;
        try {
            node = MAPPER.readTree(body);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Unexpected " + what + " response shape: " + clip(body, 500), e);
        }
        if (node == null || node.isMissingNode()) {
            throw shape(what, body);
        }
        return node;
    }

    private static IllegalArgumentException shape(String what, String body) {
        return new IllegalArgumentException("Unexpected " + what + " response shape: " + clip(body, 500));
    }

    private String redact(String s) {
        if (s == null) {
            return "";
        }
        String key = config.apiKey();
        return key == null || key.isEmpty() ? s : s.replace(key, "***");
    }

    private static String clip(String s, int n) {
        if (s == null) {
            return "";
        }
        return s.length() <= n ? s : s.substring(0, n) + "...";
    }

    private static boolean notEmpty(String s) {
        return s != null && !s.isEmpty();
    }

    /** Python-style blank test: strip() also removes non-breaking and other Unicode spaces. */
    private static boolean isBlank(String s) {
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (!(Character.isWhitespace(c) || Character.isSpaceChar(c) || c == 0x85)) {
                return false;
            }
        }
        return true;
    }

    private static String urlEncode(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }

    private static void writeText(ByteArrayOutputStream out, String s) {
        out.writeBytes(s.getBytes(StandardCharsets.UTF_8));
    }

    private static void writeField(ByteArrayOutputStream out, String boundary, String name, String value) {
        writeText(out, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n\r\n");
        writeText(out, value);
        writeText(out, "\r\n");
    }

    /** Quotes and line breaks cannot appear inside the quoted filename; percent-encode them, like httpx does. */
    private static String escapeFilename(String filename) {
        return filename.replace("\"", "%22").replace("\r", "%0D").replace("\n", "%0A");
    }
}
