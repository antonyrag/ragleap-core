package com.ragleap.rag.embedding;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class EmbeddingServiceTest {

    private HttpServer stubServer;

    /**
     * True only when a real Ollama instance is reachable at
     * localhost:11434 - genuinely live on this VPS, but never true on
     * GitHub Actions runners or any other machine without Ollama
     * installed. Live tests are skipped (not failed) when this is
     * false, via assumeTrue() - the same "skip gracefully in
     * environments that can't support it" pattern as a real CI system,
     * rather than either always failing elsewhere or lying about
     * coverage by mocking Ollama out entirely.
     */
    private static boolean isOllamaReachable() {
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            HttpRequest request = HttpRequest.newBuilder(URI.create("http://localhost:11434/api/tags"))
                    .timeout(Duration.ofSeconds(2))
                    .GET()
                    .build();
            HttpResponse<Void> response = client.send(request, HttpResponse.BodyHandlers.discarding());
            return response.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    @AfterEach
    void stopStubServer() {
        if (stubServer != null) {
            stubServer.stop(0);
        }
    }

    private EmbeddingService newService(EmbeddingConfig config, String geminiUrl, String cohereUrl, String voyageUrl) {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        return new EmbeddingService(config, client, geminiUrl, cohereUrl, voyageUrl);
    }

    // ---- LIVE tests against the real Ollama instance on this VPS ----
    // No API key needed - genuinely exercises the network path, not a mock.

    @Test
    void embedTextLiveAgainstRealOllama() {
        assumeTrue(isOllamaReachable(), "Ollama not reachable at localhost:11434 - skipping live test (expected on CI runners)");
        EmbeddingConfig config = new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null);
        EmbeddingService service = new EmbeddingService(config);

        List<Double> embedding = service.embedText("hello world");

        assertNotNull(embedding, "Ollama call failed - is Ollama running on localhost:11434 with nomic-embed-text pulled?");
        assertEquals(768, embedding.size());
        assertTrue(embedding.stream().anyMatch(v -> v != 0.0), "Embedding should not be all zeros");
    }

    @Test
    void embedBatchLiveAgainstRealOllama() {
        assumeTrue(isOllamaReachable(), "Ollama not reachable at localhost:11434 - skipping live test (expected on CI runners)");
        EmbeddingConfig config = new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null);
        EmbeddingService service = new EmbeddingService(config);

        List<List<Double>> embeddings = service.embedBatch(List.of("hello", "world"));

        assertEquals(2, embeddings.size());
        assertEquals(768, embeddings.get(0).size());
        assertEquals(768, embeddings.get(1).size());
        assertNotEquals(embeddings.get(0), embeddings.get(1));
    }

    @Test
    void embedTextReturnsNullOnBlankInputWithoutCallingNetwork() {
        EmbeddingConfig config = new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null);
        EmbeddingService service = new EmbeddingService(config);

        assertNull(service.embedText(""));
        assertNull(service.embedText("   "));
        assertNull(service.embedText(null));
    }

    @Test
    void embedBatchReturnsEmptyListForEmptyInput() {
        EmbeddingConfig config = new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null);
        EmbeddingService service = new EmbeddingService(config);

        assertEquals(List.of(), service.embedBatch(List.of()));
        assertEquals(List.of(), service.embedBatch(null));
    }

    @Test
    void embedTextReturnsNullOnUnreachableServerRatherThanThrowing() {
        EmbeddingConfig config = new EmbeddingConfig("custom", "key", "some-model", 10,
                "http://localhost:1/v1");
        EmbeddingService service = new EmbeddingService(config);

        assertNull(service.embedText("test"));
    }

    // ---- NOT live-verified: gemini, openai-compatible-shape, cohere, voyage ----
    // Verified against a local stub server standing in for the real API.

    @Test
    void embedTextParsesGeminiResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            String responseBody = "{\"embedding\": {\"values\": [0.1, 0.2, 0.3]}}";
            sendJson(exchange, responseBody);
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("gemini", "fake-key", "gemini-embedding-001", 3, null);
        EmbeddingService service = newService(config, stubUrl, "unused", "unused");

        List<Double> result = service.embedText("test");
        assertEquals(List.of(0.1, 0.2, 0.3), result);
    }

    @Test
    void embedBatchParsesGeminiBatchResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            String responseBody = "{\"embeddings\": [{\"values\": [0.1, 0.2]}, {\"values\": [0.3, 0.4]}]}";
            sendJson(exchange, responseBody);
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("gemini", "fake-key", "gemini-embedding-001", 2, null);
        EmbeddingService service = newService(config, stubUrl, "unused", "unused");

        List<List<Double>> result = service.embedBatch(List.of("a", "b"));
        assertEquals(List.of(List.of(0.1, 0.2), List.of(0.3, 0.4)), result);
    }

    @Test
    void embedTextParsesOpenAiCompatibleResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            String responseBody = "{\"data\": [{\"embedding\": [0.5, 0.6, 0.7]}]}";
            sendJson(exchange, responseBody);
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("custom", "fake-key", "some-model", 3, stubUrl);
        EmbeddingService service = new EmbeddingService(config);

        List<Double> result = service.embedText("test");
        assertEquals(List.of(0.5, 0.6, 0.7), result);
    }

    @Test
    void embedTextParsesCohereResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            String responseBody = "{\"embeddings\": [[0.1, 0.2, 0.3]]}";
            sendJson(exchange, responseBody);
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("cohere", "fake-key", "embed-v3", 3, null);
        EmbeddingService service = newService(config, "unused", stubUrl, "unused");

        List<Double> result = service.embedText("test");
        assertEquals(List.of(0.1, 0.2, 0.3), result);
    }

    @Test
    void embedTextParsesVoyageResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            String responseBody = "{\"data\": [{\"embedding\": [0.9, 0.8, 0.7]}]}";
            sendJson(exchange, responseBody);
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("voyage", "fake-key", "voyage-3", 3, null);
        EmbeddingService service = newService(config, "unused", "unused", stubUrl);

        List<Double> result = service.embedText("test");
        assertEquals(List.of(0.9, 0.8, 0.7), result);
    }

    @Test
    void embedTextReturnsNullOn4xxResponseFromProvider() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            byte[] body = "{\"error\": \"invalid api key\"}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(401, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        EmbeddingConfig config = new EmbeddingConfig("custom", "bad-key", "some-model", 3, stubUrl);
        EmbeddingService service = new EmbeddingService(config);

        assertNull(service.embedText("test"));
    }

    private static void sendJson(HttpExchange exchange, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
