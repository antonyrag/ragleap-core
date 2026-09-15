package com.ragleap.rag.generation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ragleap.rag.vectorstore.SearchResult;
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
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class GenerationServiceGenerateAnswerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private HttpServer stubServer;

    @AfterEach
    void stopStubServer() {
        if (stubServer != null) {
            stubServer.stop(0);
        }
    }

    private static ProviderConfig provider(String name, String apiKey, String model, String baseUrl) {
        return new ProviderConfig(name, apiKey, model, baseUrl, (Function<String, String>) s -> null);
    }

    private static SearchResult chunk(String text, String docName, int chunkIndex) {
        return new SearchResult("c1", text, 0.9, "d1", docName, chunkIndex);
    }

    private static boolean isOllamaReachable() {
        try {
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
            HttpRequest request = HttpRequest.newBuilder(URI.create("http://localhost:11434/api/tags"))
                    .timeout(Duration.ofSeconds(2)).GET().build();
            HttpResponse<Void> response = client.send(request, HttpResponse.BodyHandlers.discarding());
            return response.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    @Test
    void generateAnswerLiveAgainstRealOllama() {
        org.junit.jupiter.api.Assumptions.assumeTrue(isOllamaReachable(),
                "Ollama not reachable at localhost:11434 - skipping live test (expected on CI runners)");

        ProviderConfig ollama = provider("ollama", null, "qwen2.5:0.5b", null);
        GenerationService service = new GenerationService(ollama);

        List<SearchResult> chunks = List.of(chunk("RagLeap supports WhatsApp, Telegram, and voice calls.", "features.txt", 0));
        // Small maxTokens deliberately, not the 1024 default - this is a
        // smoke test proving the pipeline works end-to-end, not a quality
        // check, and a small CPU-only model generating a long response
        // under concurrent test-suite load can exceed the HTTP timeout.
        GenerationResult result = service.generateAnswer("What channels does RagLeap support?", chunks,
                null, null, 60, "", null, null);

        assertEquals("ollama", result.providerUsed());
        assertEquals("qwen2.5:0.5b", result.modelUsed());
        assertNotNull(result.answer());
        assertFalse(result.answer().isBlank());
        assertNotEquals("No answer generated.", result.answer());
        assertEquals(1, result.chunksSent());
        assertEquals(List.of("features.txt"), result.sources());
    }

    @Test
    void generateAnswerParsesGeminiResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> sendJson(exchange,
                "{\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"The answer is 42.\"}]}}], " +
                "\"usageMetadata\": {\"promptTokenCount\": 10, \"candidatesTokenCount\": 5, \"totalTokenCount\": 15}}"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("gemini", "key", "gemini-2.5-flash", null),
                List.of(), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl, "unused");

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, null);

        assertEquals("The answer is 42.", result.answer());
        assertEquals("gemini", result.providerUsed());
        assertNotNull(result.usage());
        assertEquals(10, result.usage().promptTokens());
        assertEquals(5, result.usage().completionTokens());
        assertEquals(15, result.usage().totalTokens());
    }

    @Test
    void generateAnswerParsesAnthropicResponseShapeCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> sendJson(exchange,
                "{\"content\": [{\"type\": \"text\", \"text\": \"Claude's answer here.\"}], " +
                "\"usage\": {\"input_tokens\": 20, \"output_tokens\": 8}}"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("anthropic", "key", "claude-sonnet-5", null),
                List.of(), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), "unused", stubUrl);

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, null);

        assertEquals("Claude's answer here.", result.answer());
        assertEquals("anthropic", result.providerUsed());
        assertEquals(20, result.usage().promptTokens());
        assertEquals(8, result.usage().completionTokens());
        assertEquals(28, result.usage().totalTokens());
    }

    @Test
    void generateAnswerAnthropicStructuredOutputUsesToolUseBlock() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> sendJson(exchange,
                "{\"content\": [{\"type\": \"tool_use\", \"name\": \"structured_response\", " +
                "\"input\": {\"name\": \"RagLeap\", \"count\": 3}}], \"usage\": {\"input_tokens\": 15, \"output_tokens\": 10}}"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("anthropic", "key", "claude-sonnet-5", null),
                List.of(), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), "unused", stubUrl);

        JsonNode schema = MAPPER.readTree("{\"type\": \"object\", \"properties\": {\"name\": {\"type\": \"string\"}, \"count\": {\"type\": \"integer\"}}}");
        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, schema);

        assertEquals("native", result.structuredEnforcement());
        assertTrue(result.structuredValid());
        assertEquals("RagLeap", result.structured().get("name").asText());
    }

    @Test
    void generateAnswerOpenAiCompatibleStrictJsonSchemaSucceeds() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> sendJson(exchange,
                "{\"choices\": [{\"message\": {\"content\": \"{\\\"answer\\\": \\\"yes\\\"}\"}}], " +
                "\"usage\": {\"prompt_tokens\": 5, \"completion_tokens\": 3, \"total_tokens\": 8}}"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("custom", "key", "some-model", stubUrl));
        JsonNode schema = MAPPER.readTree("{\"type\": \"object\", \"properties\": {\"answer\": {\"type\": \"string\"}}}");

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, schema);

        assertEquals("native", result.structuredEnforcement());
        assertTrue(result.structuredValid());
        assertEquals("yes", result.structured().get("answer").asText());
    }

    @Test
    void generateAnswerOpenAiCompatibleFallsBackToJsonObjectOnStrictModeFailure() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> {
            String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (body.contains("json_schema")) {
                // Simulate a provider that rejects strict mode
                byte[] err = "{\"error\": \"json_schema not supported\"}".getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(400, err.length);
                exchange.getResponseBody().write(err);
                exchange.close();
            } else {
                sendJson(exchange, "{\"choices\": [{\"message\": {\"content\": \"{\\\"answer\\\": \\\"fallback worked\\\"}\"}}]}");
            }
        });
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("custom", "key", "some-model", stubUrl));
        JsonNode schema = MAPPER.readTree("{\"type\": \"object\", \"properties\": {\"answer\": {\"type\": \"string\"}}}");

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, schema);

        assertEquals("json_object_fallback", result.structuredEnforcement());
        assertEquals("fallback worked", result.structured().get("answer").asText());
    }

    @Test
    void generateAnswerFallsBackToSecondProviderWhenFirstFails() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> sendJson(exchange,
                "{\"choices\": [{\"message\": {\"content\": \"fallback answer\"}}]}"));
        stubServer.start();
        String workingUrl = "http://localhost:" + stubServer.getAddress().getPort();

        // Primary points at a port nothing listens on - guaranteed to fail
        ProviderConfig brokenPrimary = provider("custom", "key", "model", "http://localhost:1/v1");
        ProviderConfig workingFallback = provider("custom2".equals("custom2") ? "openai" : "openai", "key", "model", workingUrl);
        // openai is a real named provider so ProviderConfig accepts it with any baseUrl override
        ProviderConfig workingFallbackConfig = new ProviderConfig("openai", "key", "model", workingUrl,
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(brokenPrimary, List.of(workingFallbackConfig),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, null);

        assertEquals("fallback answer", result.answer());
        assertEquals("openai", result.providerUsed());
    }

    @Test
    void generateAnswerReturnsFailureMessageWhenAllProvidersFail() {
        ProviderConfig broken1 = provider("custom", "key", "model", "http://localhost:1/v1");
        ProviderConfig broken2 = new ProviderConfig("openai", "key", "model", "http://localhost:2/v1",
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(broken1, List.of(broken2),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null, null);

        assertTrue(result.answer().startsWith("Sorry, all configured providers failed."));
        assertNull(result.providerUsed());
        assertEquals(List.of(), result.sources());
        assertEquals(0, result.chunksSent());
    }

    @Test
    void generateAnswerFailureWithResponseFormatSetsStructuredValidFalse() {
        ProviderConfig broken = provider("custom", "key", "model", "http://localhost:1/v1");
        GenerationService service = new GenerationService(broken);

        GenerationResult result = service.generateAnswer("q", List.of(), null, null, null, "", null,
                MAPPER.createObjectNode());

        assertEquals(Boolean.FALSE, result.structuredValid());
        assertNull(result.structured());
    }

    private static void sendJson(HttpExchange exchange, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
