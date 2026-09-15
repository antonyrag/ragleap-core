package com.ragleap.rag.generation;

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
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class GenerationServiceStreamTest {

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

    private static void sendSse(HttpExchange exchange, String sseBody) throws IOException {
        byte[] bytes = sseBody.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    @Test
    void streamOpenAiCompatibleParsesSseDeltasCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> sendSse(exchange,
                "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n" +
                "data: {\"choices\": [{\"delta\": {\"content\": \", world\"}}]}\n\n" +
                "data: {\"choices\": [{\"delta\": {}}]}\n\n" +
                "data: [DONE]\n\n"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("custom", "key", "some-model", stubUrl));
        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(List.of("Hello", ", world"), pieces);
    }

    @Test
    void streamGeminiParsesSseCandidatesCorrectly() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> sendSse(exchange,
                "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"The \"}]}}]}\n\n" +
                "data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"answer.\"}]}}]}\n\n"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("gemini", "key", "gemini-2.5-flash", null),
                List.of(), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), stubUrl, "unused");

        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(List.of("The ", "answer."), pieces);
    }

    @Test
    void streamAnthropicOnlyEmitsContentBlockDeltaTextEvents() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/", exchange -> sendSse(exchange,
                "data: {\"type\": \"message_start\"}\n\n" +
                "data: {\"type\": \"content_block_start\"}\n\n" +
                "data: {\"type\": \"content_block_delta\", \"delta\": {\"type\": \"text_delta\", \"text\": \"Hi\"}}\n\n" +
                "data: {\"type\": \"content_block_delta\", \"delta\": {\"type\": \"text_delta\", \"text\": \" there\"}}\n\n" +
                "data: {\"type\": \"message_stop\"}\n\n"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("anthropic", "key", "claude-sonnet-5", null),
                List.of(), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(), "unused", stubUrl);

        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(List.of("Hi", " there"), pieces);
    }

    @Test
    void streamFallsBackToSecondProviderWhenFirstFailsBeforeAnyPieceYielded() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> sendSse(exchange,
                "data: {\"choices\": [{\"delta\": {\"content\": \"fallback worked\"}}]}\n\n"));
        stubServer.start();
        String workingUrl = "http://localhost:" + stubServer.getAddress().getPort();

        ProviderConfig brokenPrimary = provider("custom", "key", "model", "http://localhost:1/v1");
        ProviderConfig workingFallback = new ProviderConfig("openai", "key", "model", workingUrl,
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(brokenPrimary, List.of(workingFallback),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(List.of("fallback worked"), pieces);
    }

    @Test
    void streamEmitsErrorMarkerAndStopsWhenProviderFailsAfterPartialYield() throws IOException {
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> sendSse(exchange,
                "data: {\"choices\": [{\"delta\": {\"content\": \"partial\"}}]}\n\n" +
                "data: {this is not valid json\n\n"));
        stubServer.start();
        String stubUrl = "http://localhost:" + stubServer.getAddress().getPort();

        GenerationService service = new GenerationService(provider("custom", "key", "some-model", stubUrl));
        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(2, pieces.size());
        assertEquals("partial", pieces.get(0));
        assertTrue(pieces.get(1).startsWith("\n[Error:"));
    }

    @Test
    void streamReturnsFailureMessageWhenAllProvidersFail() {
        ProviderConfig broken1 = provider("custom", "key", "model", "http://localhost:1/v1");
        ProviderConfig broken2 = new ProviderConfig("openai", "key", "model", "http://localhost:2/v1",
                (Function<String, String>) s -> null);

        GenerationService service = new GenerationService(broken1, List.of(broken2),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("q", List.<SearchResult>of(), (Double) null, (ProviderConfig) null,
                (Integer) null, "", (String) null, pieces::add);

        assertEquals(1, pieces.size());
        assertTrue(pieces.get(0).startsWith("Sorry, all configured providers failed."));
    }

    @Test
    void streamLiveAgainstRealOllama() {
        org.junit.jupiter.api.Assumptions.assumeTrue(isOllamaReachable(),
                "Ollama not reachable at localhost:11434 - skipping live test (expected on CI runners)");

        ProviderConfig ollama = provider("ollama", null, "qwen2.5:0.5b", null);
        GenerationService service = new GenerationService(ollama);

        List<SearchResult> chunks = List.of(chunk("RagLeap supports WhatsApp, Telegram, and voice calls.", "features.txt", 0));
        List<String> pieces = new ArrayList<>();
        service.generateAnswerStream("What channels does RagLeap support?", chunks, (Double) null,
                (ProviderConfig) null, (Integer) 60, "", (String) null, pieces::add);

        assertFalse(pieces.isEmpty());
        String full = String.join("", pieces);
        assertFalse(full.isBlank());
        assertFalse(full.startsWith("Sorry, all configured providers failed."));
    }
}
