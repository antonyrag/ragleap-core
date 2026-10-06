package com.ragleap.rag.ingestion;

import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Config rules checked against the Python class; provider requests checked against a local stub server that
 * records exactly what was sent. Nothing here talks to the real OpenAI or Deepgram APIs.
 */
class TranscriptionTest {

    private static final String KEY = "sk-secret-123";
    private static final byte[] AUDIO = binary();

    private static byte[] binary() {
        byte[] b = new byte[1024];
        for (int i = 0; i < b.length; i++) {
            b[i] = (byte) i;
        }
        return b;
    }

    private static Function<String, String> env(String... keysAndValues) {
        Map<String, String> m = new HashMap<>();
        for (int i = 0; i < keysAndValues.length; i += 2) {
            m.put(keysAndValues[i], keysAndValues[i + 1]);
        }
        return m::get;
    }

    private static TranscriptionConfig fromEnv(String provider, String apiKey, Function<String, String> env) {
        return new TranscriptionConfig(provider, apiKey, null, null, null, null, null, env);
    }

    // ------------------------------------------------------------------ stub server

    private static final class Stub implements AutoCloseable {
        final HttpServer server;
        volatile String method;
        volatile String pathAndQuery;
        volatile Headers headers;
        volatile byte[] body;
        volatile int status = 200;
        volatile String responseBody = "{}";

        Stub() throws IOException {
            server = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
            server.createContext("/", exchange -> {
                method = exchange.getRequestMethod();
                pathAndQuery = exchange.getRequestURI().toString();
                headers = exchange.getRequestHeaders();
                body = exchange.getRequestBody().readAllBytes();
                byte[] out = responseBody.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().add("Content-Type", "application/json");
                exchange.sendResponseHeaders(status, out.length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(out);
                }
            });
            server.start();
        }

        String url() {
            return "http://localhost:" + server.getAddress().getPort();
        }

        @Override
        public void close() {
            server.stop(0);
        }
    }

    private record Part(String name, String filename, byte[] data) {
        String text() {
            return new String(data, StandardCharsets.UTF_8);
        }
    }

    private static Map<String, Part> multipart(byte[] body, String contentType) {
        String boundary = contentType.substring(contentType.indexOf("boundary=") + "boundary=".length());
        String all = new String(body, StandardCharsets.ISO_8859_1);
        String[] segments = all.split(Pattern.quote("--" + boundary), -1);
        Map<String, Part> parts = new LinkedHashMap<>();
        for (int i = 1; i < segments.length; i++) {
            String seg = segments[i];
            if (seg.startsWith("--")) {
                break;
            }
            seg = seg.substring(2);
            int sep = seg.indexOf("\r\n\r\n");
            String head = new String(seg.substring(0, sep).getBytes(StandardCharsets.ISO_8859_1), StandardCharsets.UTF_8);
            String data = seg.substring(sep + 4);
            data = data.substring(0, data.length() - 2);
            Matcher name = Pattern.compile("name=\"([^\"]*)\"").matcher(head);
            Matcher file = Pattern.compile("filename=\"([^\"]*)\"").matcher(head);
            assertTrue(name.find(), "part without a name: " + head);
            parts.put(name.group(1), new Part(name.group(1), file.find() ? file.group(1) : null,
                    data.getBytes(StandardCharsets.ISO_8859_1)));
        }
        return parts;
    }

    private static TranscriptionService whisper(Stub stub, String language, String prompt) {
        TranscriptionConfig cfg = new TranscriptionConfig("whisper", KEY, null, language, prompt, null)
                .withBaseUrl(stub.url() + "/v1");
        return new TranscriptionService(cfg);
    }

    private static TranscriptionService deepgram(Stub stub, String language) {
        TranscriptionConfig cfg = new TranscriptionConfig("deepgram", KEY, null, language, null, null)
                .withBaseUrl(stub.url());
        return new TranscriptionService(cfg);
    }

    // ------------------------------------------------------------------ config

    @Test void whisperDefaultsUseTheEnvironmentKeyAndTheDocumentedModel() {
        TranscriptionConfig c = fromEnv("Whisper", null, env("OPENAI_API_KEY", "env-key"));
        assertEquals("whisper", c.provider());
        assertEquals("whisper-1", c.model());
        assertEquals("env-key", c.apiKey());
        assertEquals(TranscriptionConfig.DEFAULT_WHISPER_BASE_URL, c.effectiveBaseUrl());
    }

    @Test void deepgramDefaultsUseTheEnvironmentKeyAndTheDocumentedModel() {
        TranscriptionConfig c = fromEnv("DEEPGRAM", null, env("DEEPGRAM_API_KEY", "dg-key"));
        assertEquals("deepgram", c.provider());
        assertEquals("nova-2", c.model());
        assertEquals("dg-key", c.apiKey());
        assertEquals(TranscriptionConfig.DEFAULT_DEEPGRAM_BASE_URL, c.effectiveBaseUrl());
    }

    @Test void anExplicitKeyBeatsTheEnvironmentAndAnEmptyOneFallsBack() {
        assertEquals("explicit", fromEnv("whisper", "explicit", env("OPENAI_API_KEY", "env-key")).apiKey());
        assertEquals("env-key", fromEnv("whisper", "", env("OPENAI_API_KEY", "env-key")).apiKey());
    }

    @Test void aMissingKeyIsRejectedWithTheVariableNameForEachProvider() {
        IllegalArgumentException a = assertThrows(IllegalArgumentException.class, () -> fromEnv("whisper", null, env()));
        assertEquals("No API key for transcription provider 'whisper'. Pass apiKey explicitly, or set OPENAI_API_KEY in your environment.", a.getMessage());
        IllegalArgumentException b = assertThrows(IllegalArgumentException.class, () -> fromEnv("deepgram", null, env("DEEPGRAM_API_KEY", "")));
        assertEquals("No API key for transcription provider 'deepgram'. Pass apiKey explicitly, or set DEEPGRAM_API_KEY in your environment.", b.getMessage());
    }

    @Test void anUnknownProviderIsRejected() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> fromEnv("AssemblyAI", "k", env()));
        assertEquals("Unknown transcription provider 'assemblyai'. Supported: whisper, deepgram, custom.", ex.getMessage());
    }

    @Test void customNeedsAFunction() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> fromEnv("custom", null, env()));
        assertTrue(ex.getMessage().startsWith("provider='custom' requires a TranscribeFunction"));
    }

    @Test void customWithAFunctionNeedsNoKey() {
        assertEquals("custom", new TranscriptionConfig("custom", null, null, null, null, (f, b) -> "x").provider());
    }

    @Test void toStringNeverShowsTheKey() {
        String s = new TranscriptionConfig("whisper", KEY, null, "en", null, null).toString();
        assertFalse(s.contains(KEY));
        assertTrue(s.contains("***"));
    }

    @Test void baseUrlMustBeHttpOrHttpsAndLosesItsTrailingSlash() {
        TranscriptionConfig c = new TranscriptionConfig("whisper", KEY, null, null, null, null);
        assertThrows(IllegalArgumentException.class, () -> c.withBaseUrl("ftp://example.com"));
        assertThrows(IllegalArgumentException.class, () -> c.withBaseUrl("not a url"));
        assertEquals("http://localhost:1/v1", c.withBaseUrl("http://localhost:1/v1//").effectiveBaseUrl());
    }

    // ------------------------------------------------------------------ Whisper

    @Test void whisperSendsADocumentedMultipartRequest() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"text\":\"hello world\"}";
            String text = whisper(stub, "en", "Brand names: RagLeap").transcribe("meeting.mp3", AUDIO);
            assertEquals("hello world", text);
            assertEquals("POST", stub.method);
            assertEquals("/v1/audio/transcriptions", stub.pathAndQuery);
            assertEquals("Bearer " + KEY, stub.headers.getFirst("Authorization"));
            String contentType = stub.headers.getFirst("Content-Type");
            assertTrue(contentType.startsWith("multipart/form-data; boundary="));
            Map<String, Part> parts = multipart(stub.body, contentType);
            assertEquals("whisper-1", parts.get("model").text());
            assertEquals("en", parts.get("language").text());
            assertEquals("Brand names: RagLeap", parts.get("prompt").text());
            assertEquals("meeting.mp3", parts.get("file").filename());
            assertArrayEquals(AUDIO, parts.get("file").data());
        }
    }

    @Test void whisperLeavesOutLanguageAndPromptUnlessSet() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"text\":\"hi\"}";
            whisper(stub, null, "").transcribe("a.wav", AUDIO);
            Map<String, Part> parts = multipart(stub.body, stub.headers.getFirst("Content-Type"));
            assertEquals(2, parts.size());
            assertTrue(parts.containsKey("model") && parts.containsKey("file"));
        }
    }

    @Test void whisperEmptyOrBlankTranscriptionsAreRejectedWithPythonsMessage() throws Exception {
        try (Stub stub = new Stub()) {
            for (String body : new String[] {"{\"text\":\"\"}", "{\"text\":\"  \\u00a0 \"}"}) {
                stub.responseBody = body;
                IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                        () -> whisper(stub, null, null).transcribe("a.mp3", AUDIO));
                assertEquals("Whisper returned an empty transcription — check the audio has audible speech.", ex.getMessage());
            }
        }
    }

    @Test void anHttpErrorCarriesTheStatusAndNeverTheKey() throws Exception {
        try (Stub stub = new Stub()) {
            stub.status = 401;
            stub.responseBody = "{\"error\":\"Incorrect API key provided: " + KEY + "\"}";
            TranscriptionApiException ex = assertThrows(TranscriptionApiException.class,
                    () -> whisper(stub, null, null).transcribe("a.mp3", AUDIO));
            assertEquals(401, ex.getStatusCode());
            assertTrue(ex.getMessage().startsWith("Whisper request failed: HTTP 401"));
            assertFalse(ex.getMessage().contains(KEY));
            assertTrue(ex.getMessage().contains("***"));
        }
    }

    @Test void aResponseWithoutATextFieldIsAShapeError() throws Exception {
        try (Stub stub = new Stub()) {
            for (String body : new String[] {"{}", "{\"text\":5}", "not json", ""}) {
                stub.responseBody = body;
                IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                        () -> whisper(stub, null, null).transcribe("a.mp3", AUDIO), body);
                assertTrue(ex.getMessage().startsWith("Unexpected Whisper response shape"), ex.getMessage());
            }
        }
    }

    @Test void quotesAndLineBreaksInTheFilenameCannotBreakTheMultipartHeader() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"text\":\"ok\"}";
            whisper(stub, null, null).transcribe("a\"b\r\nc.mp3", AUDIO);
            Map<String, Part> parts = multipart(stub.body, stub.headers.getFirst("Content-Type"));
            assertEquals("a%22b%0D%0Ac.mp3", parts.get("file").filename());
            assertArrayEquals(AUDIO, parts.get("file").data());
        }
    }

    @Test void aUnicodeFilenameSurvives() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"text\":\"ok\"}";
            whisper(stub, null, null).transcribe("réunion-日本.mp3", AUDIO);
            assertEquals("réunion-日本.mp3", multipart(stub.body, stub.headers.getFirst("Content-Type")).get("file").filename());
        }
    }

    @Test void aRedirectIsNotFollowedSoTheKeyCannotLeak() throws Exception {
        try (Stub stub = new Stub()) {
            stub.status = 302;
            stub.responseBody = "";
            TranscriptionApiException ex = assertThrows(TranscriptionApiException.class,
                    () -> whisper(stub, null, null).transcribe("a.mp3", AUDIO));
            assertEquals(302, ex.getStatusCode());
        }
    }

    // ------------------------------------------------------------------ Deepgram

    @Test void deepgramSendsRawAudioWithTheDocumentedHeadersAndQuery() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"hello deepgram\"}]}]}}";
            assertEquals("hello deepgram", deepgram(stub, null).transcribe("a.wav", AUDIO));
            assertEquals("POST", stub.method);
            assertEquals("/v1/listen?model=nova-2&smart_format=true", stub.pathAndQuery);
            assertEquals("Token " + KEY, stub.headers.getFirst("Authorization"));
            assertEquals("audio/*", stub.headers.getFirst("Content-Type"));
            assertArrayEquals(AUDIO, stub.body);
        }
    }

    @Test void deepgramAddsTheLanguageParameterWhenSet() throws Exception {
        try (Stub stub = new Stub()) {
            stub.responseBody = "{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"hola\"}]}]}}";
            deepgram(stub, "es").transcribe("a.wav", AUDIO);
            assertEquals("/v1/listen?model=nova-2&smart_format=true&language=es", stub.pathAndQuery);
        }
    }

    @Test void deepgramEmptyOrNullTranscriptsAreRejectedWithPythonsMessage() throws Exception {
        try (Stub stub = new Stub()) {
            for (String t : new String[] {"\"\"", "\"   \"", "null"}) {
                stub.responseBody = "{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":" + t + "}]}]}}";
                IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                        () -> deepgram(stub, null).transcribe("a.wav", AUDIO), t);
                assertEquals("Deepgram returned an empty transcription — check the audio has audible speech.", ex.getMessage());
            }
        }
    }

    @Test void deepgramUnexpectedResponseShapesAreRejected() throws Exception {
        try (Stub stub = new Stub()) {
            for (String body : new String[] {"{}", "{\"results\":{\"channels\":[]}}", "{\"results\":{\"channels\":[{\"alternatives\":[]}]}}", "oops"}) {
                stub.responseBody = body;
                IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                        () -> deepgram(stub, null).transcribe("a.wav", AUDIO), body);
                assertTrue(ex.getMessage().startsWith("Unexpected Deepgram response shape"), ex.getMessage());
            }
        }
    }

    @Test void deepgramHttpErrorsCarryTheStatus() throws Exception {
        try (Stub stub = new Stub()) {
            stub.status = 500;
            stub.responseBody = "boom";
            TranscriptionApiException ex = assertThrows(TranscriptionApiException.class,
                    () -> deepgram(stub, null).transcribe("a.wav", AUDIO));
            assertEquals(500, ex.getStatusCode());
            assertTrue(ex.getMessage().startsWith("Deepgram request failed: HTTP 500"));
        }
    }

    // ------------------------------------------------------------------ transport and custom

    @Test void aConnectionFailureIsATranscriptionApiExceptionWithoutAStatus() {
        TranscriptionConfig cfg = new TranscriptionConfig("whisper", KEY, null, null, null, null).withBaseUrl("http://localhost:1/v1");
        TranscriptionApiException ex = assertThrows(TranscriptionApiException.class,
                () -> new TranscriptionService(cfg).transcribe("a.mp3", AUDIO));
        assertEquals(-1, ex.getStatusCode());
        assertTrue(ex.getMessage().startsWith("Whisper request failed"));
        assertFalse(ex.getMessage().contains(KEY));
    }

    @Test void theCustomProviderGetsTheFilenameAndBytesAndItsResultIsReturned() {
        AtomicReference<String> name = new AtomicReference<>();
        AtomicReference<byte[]> bytes = new AtomicReference<>();
        TranscriptionConfig cfg = new TranscriptionConfig("custom", null, null, null, null, (f, b) -> {
            name.set(f);
            bytes.set(b);
            return "custom text";
        });
        assertEquals("custom text", new TranscriptionService(cfg).transcribe("a.wav", AUDIO));
        assertEquals("a.wav", name.get());
        assertArrayEquals(AUDIO, bytes.get());
    }
}
