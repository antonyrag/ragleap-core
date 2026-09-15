package com.ragleap.rag.generation;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class GenerationServiceDescribeImageTest {

    private HttpServer stubServer;
    private volatile String lastRequestBody;

    @AfterEach
    void stopStubServer() {
        if (stubServer != null) {
            stubServer.stop(0);
        }
    }

    private static ProviderConfig provider(String name, String apiKey, String model, String baseUrl) {
        return new ProviderConfig(name, apiKey, model, baseUrl, (Function<String, String>) s -> null);
    }

    private void startStub(String responseJson) throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> {
            lastRequestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] bytes = responseJson.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        stubServer.start();
    }

    private String stubUrl() {
        return "http://localhost:" + stubServer.getAddress().getPort();
    }

    @Test
    void describeImageUsesGeminiFromFallbackChainWhenPrimaryIsNotGemini() throws Exception {
        startStub("{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"A photo of a cat.\"}]}}]}");

        ProviderConfig customPrimary = provider("custom", "key", "some-model", "http://localhost:1/v1");
        ProviderConfig geminiFallback = new ProviderConfig("gemini", "gkey", "gemini-2.5-flash", null,
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(customPrimary, List.of(geminiFallback),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl(), "unused");

        String description = service.describeImage(new byte[]{1, 2, 3}, "image/png", null);

        assertEquals("A photo of a cat.", description);
        assertTrue(lastRequestBody.contains("image/png"));
    }

    @Test
    void describeImageThrowsWhenNoGeminiConfigInChain() {
        ProviderConfig customPrimary = provider("custom", "key", "some-model", "http://localhost:1/v1");
        ProviderConfig openaiFallback = new ProviderConfig("openai", "key", "model", "http://localhost:2/v1",
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(customPrimary, List.of(openaiFallback),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> service.describeImage(new byte[]{1, 2, 3}));
        assertTrue(ex.getMessage().contains("Gemini"));
    }

    @Test
    void describeImageUsesDefaultPromptWhenNoneProvided() throws Exception {
        startStub("{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Described.\"}]}}]}");

        ProviderConfig gemini = provider("gemini", "key", "gemini-2.5-flash", null);
        GenerationService service = new GenerationService(gemini, List.of(),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl(), "unused");

        service.describeImage(new byte[]{1, 2, 3});

        assertTrue(lastRequestBody.contains("Describe this image in detail"));
    }

    @Test
    void describeImageUsesProvidedPromptWhenGiven() throws Exception {
        startStub("{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Described.\"}]}}]}");

        ProviderConfig gemini = provider("gemini", "key", "gemini-2.5-flash", null);
        GenerationService service = new GenerationService(gemini, List.of(),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl(), "unused");

        service.describeImage(new byte[]{1, 2, 3}, "image/jpeg", "What color is the car?");

        assertTrue(lastRequestBody.contains("What color is the car?"));
        assertFalse(lastRequestBody.contains("Describe this image in detail"));
    }

    @Test
    void describeImageThrowsWhenModelReturnsEmptyText() throws IOException {
        startStub("{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"   \"}]}}]}");

        ProviderConfig gemini = provider("gemini", "key", "gemini-2.5-flash", null);
        GenerationService service = new GenerationService(gemini, List.of(),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl(), "unused");

        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> service.describeImage(new byte[]{1, 2, 3}));
        assertTrue(ex.getMessage().contains("no description"));
    }
}
