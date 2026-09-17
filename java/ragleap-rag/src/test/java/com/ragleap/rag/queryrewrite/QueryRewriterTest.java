package com.ragleap.rag.queryrewrite;

import com.ragleap.rag.generation.GenerationService;
import com.ragleap.rag.generation.ProviderConfig;
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
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class QueryRewriterTest {

    private HttpServer stubServer;
    private final AtomicInteger requestCount = new AtomicInteger(0);

    @AfterEach
    void stopStubServer() {
        if (stubServer != null) {
            stubServer.stop(0);
        }
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

    private String startStubReturningContent(String content) throws IOException {
        String json = "{\"choices\": [{\"message\": {\"content\": " + jsonQuote(content) + "}}]}";
        stubServer = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
        stubServer.createContext("/chat/completions", exchange -> {
            requestCount.incrementAndGet();
            byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        stubServer.start();
        return "http://localhost:" + stubServer.getAddress().getPort();
    }

    private static String jsonQuote(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }

    private static SearchResult chunk(String chunkId, String documentId, int chunkIndex) {
        return new SearchResult(chunkId, "text", 0.9, documentId, "doc.txt", chunkIndex);
    }

    // --- contextualRewrite ---

    @Test
    void contextualRewriteReturnsOriginalQueryUnchangedWhenNoHistory() throws IOException {
        String stubUrl = startStubReturningContent("should never be requested");
        GenerationService generator = new GenerationService(new ProviderConfig("custom", "key", "model", stubUrl));

        QueryRewriteResult result = QueryRewriter.contextualRewrite(generator, "What channels?", "", null);

        assertEquals("What channels?", result.query());
        assertNull(result.rawResult());
        assertEquals(0, requestCount.get(), "no LLM call should be made when there's no history");
    }

    @Test
    void contextualRewriteUsesStubbedRewrittenQuestion() throws IOException {
        String stubUrl = startStubReturningContent("What channels does RagLeap support overall?");
        GenerationService generator = new GenerationService(new ProviderConfig("custom", "key", "model", stubUrl));

        QueryRewriteResult result = QueryRewriter.contextualRewrite(
                generator, "What about those?", "Previous conversation:\nUser: Tell me about RagLeap\n\n", null);

        assertEquals("What channels does RagLeap support overall?", result.query());
        assertNotNull(result.rawResult());
        assertEquals("custom", result.rawResult().providerUsed());
        assertEquals(1, requestCount.get());
    }

    @Test
    void contextualRewriteUsesProviderFailureMessageAsRewrittenQueryWhenAllProvidersFail() {
        // Documents real, faithful-port behavior: generateAnswer() never
        // throws, so the try/catch here never fires from a provider
        // failure. Its "Sorry, all configured providers failed..."
        // message is a non-blank string, so it becomes the "rewritten"
        // query - matching the Python source's plain truthy-string
        // check exactly, even though it looks surprising.
        ProviderConfig broken = new ProviderConfig("custom", "key", "model", "http://localhost:1/v1");
        GenerationService generator = new GenerationService(broken);

        QueryRewriteResult result = QueryRewriter.contextualRewrite(generator, "What about those?", "some history\n\n", null);

        assertTrue(result.query().startsWith("Sorry, all configured providers failed."));
        assertNotNull(result.rawResult());
        assertNull(result.rawResult().providerUsed());
    }

    // --- hydeDocument ---

    @Test
    void hydeDocumentUsesStubbedHypotheticalPassage() throws IOException {
        String stubUrl = startStubReturningContent("RagLeap supports WhatsApp, Telegram, and voice calls for customer support.");
        GenerationService generator = new GenerationService(new ProviderConfig("custom", "key", "model", stubUrl));

        QueryRewriteResult result = QueryRewriter.hydeDocument(generator, "What channels does RagLeap support?", null);

        assertEquals("RagLeap supports WhatsApp, Telegram, and voice calls for customer support.", result.query());
        assertNotNull(result.rawResult());
    }

    @Test
    void hydeDocumentLiveAgainstRealOllama() {
        org.junit.jupiter.api.Assumptions.assumeTrue(isOllamaReachable(),
                "Ollama not reachable at localhost:11434 - skipping live test (expected on CI runners)");

        GenerationService generator = new GenerationService(new ProviderConfig("ollama", null, "qwen2.5:0.5b", null));

        QueryRewriteResult result = QueryRewriter.hydeDocument(generator, "What channels does RagLeap support?", null);

        assertNotNull(result.query());
        assertFalse(result.query().isBlank());
        assertNotNull(result.rawResult());
        assertEquals("ollama", result.rawResult().providerUsed());
    }

    // --- multiQueryVariants ---

    @Test
    void multiQueryVariantsStripsBulletsAndDedupesOriginalCaseInsensitively() throws IOException {
        String original = "What channels does RagLeap support?";
        String stubUrl = startStubReturningContent(
                "- Which channels does RagLeap support?\n" +
                "* what channels does ragleap support?\n" +
                "\tHow does RagLeap handle multiple channels?\n");
        GenerationService generator = new GenerationService(new ProviderConfig("custom", "key", "model", stubUrl));

        MultiQueryResult result = QueryRewriter.multiQueryVariants(generator, original, null);

        assertEquals(List.of(
                original,
                "Which channels does RagLeap support?",
                "How does RagLeap handle multiple channels?"
        ), result.variants());
    }

    @Test
    void multiQueryVariantsTruncatesToRequestedN() throws IOException {
        String stubUrl = startStubReturningContent(
                "Variant one\nVariant two\nVariant three\nVariant four\nVariant five\n");
        GenerationService generator = new GenerationService(new ProviderConfig("custom", "key", "model", stubUrl));

        MultiQueryResult result = QueryRewriter.multiQueryVariants(generator, "original query", 2, null);

        assertEquals(2, result.variants().size());
        assertEquals("original query", result.variants().get(0));
        assertEquals("Variant one", result.variants().get(1));
    }

    @Test
    void multiQueryVariantsIncludesProviderFailureMessageAsAVariantWhenAllProvidersFail() {
        // Same documented real behavior as contextualRewrite's failure
        // test: the failure message is a single non-blank "line", so it
        // becomes an extra variant rather than triggering the [query]
        // fallback (that fallback only fires on an actual Java exception,
        // which generateAnswer never throws).
        ProviderConfig broken = new ProviderConfig("custom", "key", "model", "http://localhost:1/v1");
        GenerationService generator = new GenerationService(broken);

        MultiQueryResult result = QueryRewriter.multiQueryVariants(generator, "original query", null);

        assertEquals(2, result.variants().size());
        assertEquals("original query", result.variants().get(0));
        assertTrue(result.variants().get(1).startsWith("Sorry, all configured providers failed."));
    }

    // --- reciprocalRankFusion ---

    @Test
    void reciprocalRankFusionMergesAndScoresByRankAcrossLists() {
        SearchResult a = chunk("a", "doc1", 0);
        SearchResult b = chunk("b", "doc1", 1);
        SearchResult c = chunk("c", "doc2", 0);

        List<SearchResult> denseRanked = List.of(a, b, c);
        List<SearchResult> sparseRanked = List.of(b, a, c);

        List<SearchResult> fused = QueryRewriter.reciprocalRankFusion(List.of(denseRanked, sparseRanked));

        // a: 1/(60+1) + 1/(60+2) = 0.016393... + 0.016129... = 0.032523
        // b: 1/(60+2) + 1/(60+1) = same total as a, but b appears
        //    first in chunkByKey via denseRanked's first occurrence at
        //    rank 1 - scores tie exactly with a, so original insertion
        //    order (a before b) must win the stable-sort tie-break.
        // c: 1/(60+3) + 1/(60+3) = 0.032258 - lowest of the three
        assertEquals(3, fused.size());
        assertEquals("c", fused.get(2).chunkId(), "c has the lowest combined RRF score, must rank last");
        assertEquals(List.of("a", "b"), List.of(fused.get(0).chunkId(), fused.get(1).chunkId()));
    }

    @Test
    void reciprocalRankFusionDedupesUsingDocumentIdAndChunkIndexWhenChunkIdMissing() {
        SearchResult noIdFirst = chunk(null, "doc1", 5);
        SearchResult noIdSecond = chunk(null, "doc1", 5);

        List<SearchResult> fused = QueryRewriter.reciprocalRankFusion(List.of(List.of(noIdFirst), List.of(noIdSecond)));

        assertEquals(1, fused.size(), "same (documentId, chunkIndex) with no chunkId must dedupe to one entry");
    }

    @Test
    void reciprocalRankFusionRespectsCustomK() {
        SearchResult a = chunk("a", "doc1", 0);
        List<SearchResult> ranked = List.of(a);

        List<SearchResult> fusedDefaultK = QueryRewriter.reciprocalRankFusion(List.of(ranked));
        List<SearchResult> fusedCustomK = QueryRewriter.reciprocalRankFusion(List.of(ranked), 0);

        assertEquals(1, fusedDefaultK.size());
        assertEquals(1, fusedCustomK.size());
        assertEquals("a", fusedDefaultK.get(0).chunkId());
        assertEquals("a", fusedCustomK.get(0).chunkId());
    }
}
