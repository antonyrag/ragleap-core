package com.ragleap.rag.generation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ragleap.rag.vectorstore.SearchResult;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;
import java.util.logging.Logger;
import java.util.stream.Stream;

/**
 * Generates a grounded answer using the configured provider, with an
 * optional fallback chain, streaming, and real token usage reporting.
 * Java port of ragleap-rag's generation.py - GenerationService.
 *
 * Chunks are represented as com.ragleap.rag.vectorstore.SearchResult
 * rather than a duplicate shape - its fields (text, documentName,
 * chunkIndex, documentId, chunkId) already match exactly what the
 * Python source's chunk dicts carry into this class.
 *
 * describeImage() (Gemini vision) is a deliberate follow-up PR, same
 * split strategy used for the rest of this module.
 */
public class GenerationService {

    private static final Logger logger = Logger.getLogger(GenerationService.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static final String DEFAULT_SYSTEM_PROMPT =
            "You are a helpful assistant that answers questions using ONLY the provided context.\n" +
            "If the answer is not in the context, say clearly that you don't have that information — do not make things up.\n" +
            "Always be concise and cite which document your answer came from when possible.";

    private static final String DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com";
    private static final String DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com";
    private static final int REQUEST_TIMEOUT_SECONDS = 180;

    private final ProviderConfig primary;
    private final List<ProviderConfig> fallbacks;
    private final double defaultTemperature;
    private final int defaultMaxTokens;
    private final int maxContextChars;
    private final String systemPrompt;
    private final HttpClient httpClient;
    private final String geminiBaseUrl;
    private final String anthropicBaseUrl;

    public GenerationService(ProviderConfig primary) {
        this(primary, List.of(), 0.3, 1024, 12000, DEFAULT_SYSTEM_PROMPT);
    }

    public GenerationService(ProviderConfig primary, List<ProviderConfig> fallbacks,
                               double defaultTemperature, int defaultMaxTokens,
                               int maxContextChars, String systemPrompt) {
        this(primary, fallbacks, defaultTemperature, defaultMaxTokens, maxContextChars, systemPrompt,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build(),
                DEFAULT_GEMINI_BASE_URL, DEFAULT_ANTHROPIC_BASE_URL);
    }

    GenerationService(ProviderConfig primary, List<ProviderConfig> fallbacks,
                        double defaultTemperature, int defaultMaxTokens,
                        int maxContextChars, String systemPrompt,
                        HttpClient httpClient, String geminiBaseUrl, String anthropicBaseUrl) {
        this.primary = primary;
        this.fallbacks = fallbacks != null ? fallbacks : List.of();
        this.defaultTemperature = defaultTemperature;
        this.defaultMaxTokens = defaultMaxTokens;
        this.maxContextChars = maxContextChars;
        this.systemPrompt = systemPrompt;
        this.httpClient = httpClient;
        this.geminiBaseUrl = geminiBaseUrl;
        this.anthropicBaseUrl = anthropicBaseUrl;
    }

    public ProviderConfig getPrimary() { return primary; }
    public List<ProviderConfig> getFallbacks() { return fallbacks; }
    public double getDefaultTemperature() { return defaultTemperature; }
    public int getDefaultMaxTokens() { return defaultMaxTokens; }
    public int getMaxContextChars() { return maxContextChars; }
    public String getSystemPrompt() { return systemPrompt; }

    List<ProviderConfig> chain(ProviderConfig overrideProvider) {
        if (overrideProvider != null) {
            return List.of(overrideProvider);
        }
        List<ProviderConfig> result = new ArrayList<>();
        result.add(primary);
        for (ProviderConfig f : fallbacks) {
            if (!f.getProvider().equals(primary.getProvider())) {
                result.add(f);
            }
        }
        return result;
    }

    List<SearchResult> trimChunksToBudget(List<SearchResult> chunks) {
        if (maxContextChars <= 0 || chunks == null || chunks.isEmpty()) {
            return chunks;
        }
        List<SearchResult> kept = new ArrayList<>();
        int runningTotal = 0;
        for (SearchResult chunk : chunks) {
            String text = chunk.text() != null ? chunk.text() : "";
            int chunkLen = text.length();
            if (runningTotal + chunkLen > maxContextChars && !kept.isEmpty()) {
                break;
            }
            kept.add(chunk);
            runningTotal += chunkLen;
        }
        if (kept.size() < chunks.size()) {
            int finalTotal = runningTotal;
            logger.info(() -> String.format("Trimmed context: %d -> %d chunks (%d chars)",
                    chunks.size(), kept.size(), finalTotal));
        }
        return kept;
    }

    String buildContext(List<SearchResult> chunks) {
        if (chunks == null || chunks.isEmpty()) {
            return "No relevant context was found.";
        }
        List<String> parts = new ArrayList<>();
        int i = 1;
        for (SearchResult chunk : chunks) {
            String docName = chunk.documentName() != null ? chunk.documentName() : "unknown document";
            String text = chunk.text() != null ? chunk.text() : "";
            parts.add(String.format("[Source %d: %s, chunk %d]\n%s", i, docName, chunk.chunkIndex(), text));
            i++;
        }
        return String.join("\n\n", parts);
    }

    List<Citation> buildCitations(List<SearchResult> chunks) {
        List<Citation> citations = new ArrayList<>();
        if (chunks == null) {
            return citations;
        }
        int i = 1;
        for (SearchResult chunk : chunks) {
            String text = chunk.text() != null ? chunk.text() : "";
            String docName = chunk.documentName() != null ? chunk.documentName() : "unknown document";
            String preview = text.length() > 150 ? text.substring(0, 150) + "..." : text;
            citations.add(new Citation(i, docName, chunk.documentId(), chunk.chunkId(), chunk.chunkIndex(), preview));
            i++;
        }
        return citations;
    }

    String buildPrompt(String query, List<SearchResult> chunks, String systemPromptOverride, String historyPrefix) {
        String context = buildContext(chunks);
        String instructions = systemPromptOverride != null ? systemPromptOverride : this.systemPrompt;
        String prefix = historyPrefix != null ? historyPrefix : "";
        return instructions + "\n\n" + prefix + "Context:\n" + context + "\n\nQuestion: " + query + "\nAnswer:";
    }

    public GenerationResult generateAnswer(String query, List<SearchResult> chunks, Double temperature,
            ProviderConfig overrideProvider, Integer maxTokens, String historyPrefix,
            String systemPromptOverride, JsonNode responseFormat) {

        List<SearchResult> trimmed = trimChunksToBudget(chunks);
        String prompt = buildPrompt(query, trimmed, systemPromptOverride, historyPrefix);
        List<Citation> citations = buildCitations(trimmed);

        List<String> sources = new ArrayList<>();
        for (SearchResult c : trimmed != null ? trimmed : List.<SearchResult>of()) {
            String name = c.documentName() != null ? c.documentName() : "unknown document";
            if (!sources.contains(name)) {
                sources.add(name);
            }
        }

        double temp = temperature != null ? temperature : defaultTemperature;
        int tokens = maxTokens != null ? maxTokens : defaultMaxTokens;
        int chunksSent = trimmed != null ? trimmed.size() : 0;

        for (ProviderConfig provider : chain(overrideProvider)) {
            try {
                ProviderCallResult result = callProvider(provider, prompt, temp, tokens, responseFormat);
                return new GenerationResult(result.answer, sources, citations, provider.getProvider(),
                        provider.getModel(), result.usage, chunksSent,
                        result.structured, result.structuredValid, result.structuredEnforcement,
                        result.structuredValidationMethod);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                logger.warning(() -> "Provider '" + provider.getProvider() + "' interrupted: " + e.getMessage());
            } catch (Exception e) {
                logger.warning(() -> "Provider '" + provider.getProvider() + "' failed: " + e.getMessage());
            }
        }

        return new GenerationResult(
                "Sorry, all configured providers failed. Please try again later or contact support.",
                List.of(), List.of(), null, null, null, 0,
                null, responseFormat != null ? Boolean.FALSE : null, null, null);
    }

    public void generateAnswerStream(String query, List<SearchResult> chunks, Double temperature,
            ProviderConfig overrideProvider, Integer maxTokens, String historyPrefix,
            String systemPromptOverride, Consumer<String> onPiece) {

        double temp = temperature != null ? temperature : defaultTemperature;
        int tokens = maxTokens != null ? maxTokens : defaultMaxTokens;

        List<SearchResult> trimmed = trimChunksToBudget(chunks);
        String prompt = buildPrompt(query, trimmed, systemPromptOverride, historyPrefix);

        Exception lastError = null;
        for (ProviderConfig provider : chain(overrideProvider)) {
            boolean[] yielded = {false};
            try {
                streamProvider(provider, prompt, temp, tokens, piece -> {
                    yielded[0] = true;
                    onPiece.accept(piece);
                });
                return;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                lastError = e;
            } catch (Exception e) {
                lastError = e;
                logger.warning(() -> "Provider '" + provider.getProvider() + "' failed during streaming: " + e.getMessage());
                if (yielded[0]) {
                    onPiece.accept("\n[Error: generation interrupted — " + e.getMessage() + "]");
                    return;
                }
            }
        }

        onPiece.accept("Sorry, all configured providers failed. Last error: "
                + (lastError != null ? lastError.getMessage() : "unknown"));
    }

    private ProviderCallResult callProvider(ProviderConfig provider, String prompt, double temperature,
            int maxTokens, JsonNode responseFormat) throws IOException, InterruptedException {
        switch (provider.getProvider()) {
            case "gemini":
                return callGemini(provider, prompt, temperature, maxTokens, responseFormat);
            case "anthropic":
                return callAnthropic(provider, prompt, temperature, maxTokens, responseFormat);
            default:
                return callOpenAiCompatible(provider, prompt, temperature, maxTokens, responseFormat);
        }
    }

    private void streamProvider(ProviderConfig provider, String prompt, double temperature, int maxTokens,
            Consumer<String> onPiece) throws IOException, InterruptedException {
        switch (provider.getProvider()) {
            case "gemini":
                streamGemini(provider, prompt, temperature, maxTokens, onPiece);
                break;
            case "anthropic":
                streamAnthropic(provider, prompt, temperature, maxTokens, onPiece);
                break;
            default:
                streamOpenAiCompatible(provider, prompt, temperature, maxTokens, onPiece);
        }
    }

    private ProviderCallResult callGemini(ProviderConfig provider, String prompt, double temperature,
            int maxTokens, JsonNode responseFormat) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        ArrayNode contents = body.putArray("contents");
        ObjectNode content = contents.addObject();
        ArrayNode parts = content.putArray("parts");
        parts.addObject().put("text", prompt);
        ObjectNode generationConfig = body.putObject("generationConfig");
        generationConfig.put("temperature", temperature);
        generationConfig.put("maxOutputTokens", maxTokens);
        if (responseFormat != null) {
            generationConfig.put("responseMimeType", "application/json");
            generationConfig.set("responseSchema", responseFormat);
        }

        String base = geminiBaseUrl != null ? geminiBaseUrl : DEFAULT_GEMINI_BASE_URL;
        String url = base + "/v1beta/models/" + provider.getModel() + ":generateContent?key=" + provider.getApiKey();

        JsonNode resp = postJson(url, body.toString(), null);
        String text = resp.path("candidates").path(0).path("content").path("parts").path(0).path("text").asText("");

        Usage usage = null;
        JsonNode um = resp.path("usageMetadata");
        if (!um.isMissingNode()) {
            usage = new Usage(um.path("promptTokenCount").asInt(0), um.path("candidatesTokenCount").asInt(0),
                    um.path("totalTokenCount").asInt(0));
        }

        if (responseFormat == null) {
            return new ProviderCallResult(text, usage, null, null, null, null);
        }
        try {
            JsonNode structured = MAPPER.readTree(text);
            return new ProviderCallResult(text, usage, structured, Boolean.TRUE, "native", null);
        } catch (Exception e) {
            return new ProviderCallResult(text, usage, null, Boolean.FALSE, "native", null);
        }
    }

    private void streamGemini(ProviderConfig provider, String prompt, double temperature, int maxTokens,
            Consumer<String> onPiece) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        ArrayNode contents = body.putArray("contents");
        ObjectNode content = contents.addObject();
        ArrayNode parts = content.putArray("parts");
        parts.addObject().put("text", prompt);
        ObjectNode generationConfig = body.putObject("generationConfig");
        generationConfig.put("temperature", temperature);
        generationConfig.put("maxOutputTokens", maxTokens);

        String base = geminiBaseUrl != null ? geminiBaseUrl : DEFAULT_GEMINI_BASE_URL;
        String url = base + "/v1beta/models/" + provider.getModel()
                + ":streamGenerateContent?alt=sse&key=" + provider.getApiKey();

        consumeSse(url, body.toString(), null, data -> {
            JsonNode node = parseOrThrow(data);
            String text = node.path("candidates").path(0).path("content").path("parts").path(0).path("text").asText(null);
            if (text != null && !text.isEmpty()) {
                onPiece.accept(text);
            }
        });
    }

    private ProviderCallResult callAnthropic(ProviderConfig provider, String prompt, double temperature,
            int maxTokens, JsonNode responseFormat) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("model", provider.getModel());
        body.put("max_tokens", maxTokens);
        body.put("temperature", temperature);
        ArrayNode messages = body.putArray("messages");
        ObjectNode userMsg = messages.addObject();
        userMsg.put("role", "user");
        userMsg.put("content", prompt);

        if (responseFormat != null) {
            ArrayNode tools = body.putArray("tools");
            ObjectNode tool = tools.addObject();
            tool.put("name", "structured_response");
            tool.put("description", "Return the answer in the required structured format.");
            tool.set("input_schema", responseFormat);
            ObjectNode toolChoice = body.putObject("tool_choice");
            toolChoice.put("type", "tool");
            toolChoice.put("name", "structured_response");
        }

        String base = anthropicBaseUrl != null ? anthropicBaseUrl : DEFAULT_ANTHROPIC_BASE_URL;
        String url = base + "/v1/messages";

        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-api-key", provider.getApiKey());
        headers.put("anthropic-version", "2023-06-01");

        JsonNode resp = postJson(url, body.toString(), headers);

        Usage usage = null;
        JsonNode um = resp.path("usage");
        if (!um.isMissingNode()) {
            int in = um.path("input_tokens").asInt(0);
            int out = um.path("output_tokens").asInt(0);
            usage = new Usage(in, out, in + out);
        }

        JsonNode contentArr = resp.path("content");
        if (responseFormat != null) {
            for (JsonNode block : contentArr) {
                if ("tool_use".equals(block.path("type").asText())) {
                    JsonNode structured = block.path("input");
                    return new ProviderCallResult(structured.toString(), usage, structured, Boolean.TRUE, "native", null);
                }
            }
            return new ProviderCallResult(null, usage, null, Boolean.FALSE, "native", null);
        }

        String text = "";
        for (JsonNode block : contentArr) {
            if ("text".equals(block.path("type").asText())) {
                text = block.path("text").asText("");
                break;
            }
        }
        return new ProviderCallResult(text, usage, null, null, null, null);
    }

    private void streamAnthropic(ProviderConfig provider, String prompt, double temperature, int maxTokens,
            Consumer<String> onPiece) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("model", provider.getModel());
        body.put("max_tokens", maxTokens);
        body.put("temperature", temperature);
        body.put("stream", true);
        ArrayNode messages = body.putArray("messages");
        ObjectNode userMsg = messages.addObject();
        userMsg.put("role", "user");
        userMsg.put("content", prompt);

        String base = anthropicBaseUrl != null ? anthropicBaseUrl : DEFAULT_ANTHROPIC_BASE_URL;
        String url = base + "/v1/messages";

        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-api-key", provider.getApiKey());
        headers.put("anthropic-version", "2023-06-01");

        consumeSse(url, body.toString(), headers, data -> {
            JsonNode node = parseOrThrow(data);
            if ("content_block_delta".equals(node.path("type").asText())) {
                JsonNode delta = node.path("delta");
                if ("text_delta".equals(delta.path("type").asText())) {
                    String text = delta.path("text").asText(null);
                    if (text != null && !text.isEmpty()) {
                        onPiece.accept(text);
                    }
                }
            }
        });
    }

    private ProviderCallResult callOpenAiCompatible(ProviderConfig provider, String prompt, double temperature,
            int maxTokens, JsonNode responseFormat) throws IOException, InterruptedException {
        String url = provider.getBaseUrl() + "/chat/completions";
        Map<String, String> headers = new LinkedHashMap<>();
        if (provider.getApiKey() != null) {
            headers.put("Authorization", "Bearer " + provider.getApiKey());
        }

        if (responseFormat != null) {
            ObjectNode strictBody = buildOpenAiBody(provider, prompt, temperature, maxTokens);
            ObjectNode responseFormatNode = strictBody.putObject("response_format");
            responseFormatNode.put("type", "json_schema");
            ObjectNode jsonSchema = responseFormatNode.putObject("json_schema");
            jsonSchema.put("name", "structured_response");
            jsonSchema.put("strict", true);
            jsonSchema.set("schema", responseFormat);

            JsonNode strictResp = postJsonAllowError(url, strictBody.toString(), headers);
            if (strictResp != null) {
                String content = strictResp.path("choices").path(0).path("message").path("content").asText("");
                Usage usage = parseOpenAiUsage(strictResp);
                try {
                    JsonNode structured = MAPPER.readTree(content);
                    return new ProviderCallResult(content, usage, structured, Boolean.TRUE, "native", null);
                } catch (Exception e) {
                    return new ProviderCallResult(content, usage, null, Boolean.FALSE, "native", null);
                }
            }

            ObjectNode fallbackBody = buildOpenAiBody(provider, prompt, temperature, maxTokens);
            fallbackBody.putObject("response_format").put("type", "json_object");
            JsonNode fallbackResp = postJson(url, fallbackBody.toString(), headers);
            String content = fallbackResp.path("choices").path(0).path("message").path("content").asText("");
            Usage usage = parseOpenAiUsage(fallbackResp);
            try {
                JsonNode structured = MAPPER.readTree(content);
                return new ProviderCallResult(content, usage, structured, Boolean.TRUE, "json_object_fallback", null);
            } catch (Exception e) {
                return new ProviderCallResult(content, usage, null, Boolean.FALSE, "json_object_fallback", null);
            }
        }

        ObjectNode plainBody = buildOpenAiBody(provider, prompt, temperature, maxTokens);
        JsonNode resp = postJson(url, plainBody.toString(), headers);
        String content = resp.path("choices").path(0).path("message").path("content").asText("");
        Usage usage = parseOpenAiUsage(resp);
        return new ProviderCallResult(content, usage, null, null, null, null);
    }

    private void streamOpenAiCompatible(ProviderConfig provider, String prompt, double temperature, int maxTokens,
            Consumer<String> onPiece) throws IOException, InterruptedException {
        ObjectNode body = buildOpenAiBody(provider, prompt, temperature, maxTokens);
        body.put("stream", true);

        String url = provider.getBaseUrl() + "/chat/completions";
        Map<String, String> headers = new LinkedHashMap<>();
        if (provider.getApiKey() != null) {
            headers.put("Authorization", "Bearer " + provider.getApiKey());
        }

        consumeSse(url, body.toString(), headers, data -> {
            if ("[DONE]".equals(data)) {
                return;
            }
            JsonNode node = parseOrThrow(data);
            String delta = node.path("choices").path(0).path("delta").path("content").asText(null);
            if (delta != null && !delta.isEmpty()) {
                onPiece.accept(delta);
            }
        });
    }

    private static ObjectNode buildOpenAiBody(ProviderConfig provider, String prompt, double temperature, int maxTokens) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("model", provider.getModel());
        ArrayNode messages = body.putArray("messages");
        ObjectNode userMsg = messages.addObject();
        userMsg.put("role", "user");
        userMsg.put("content", prompt);
        body.put("temperature", temperature);
        body.put("max_tokens", maxTokens);
        return body;
    }

    private static Usage parseOpenAiUsage(JsonNode resp) {
        JsonNode u = resp.path("usage");
        if (u.isMissingNode()) {
            return null;
        }
        return new Usage(u.path("prompt_tokens").asInt(0), u.path("completion_tokens").asInt(0),
                u.path("total_tokens").asInt(0));
    }

    private static JsonNode parseOrThrow(String json) {
        try {
            return MAPPER.readTree(json);
        } catch (Exception e) {
            throw new RuntimeException("Malformed SSE data payload: " + e.getMessage(), e);
        }
    }

    private JsonNode postJson(String url, String body, Map<String, String> headers)
            throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(REQUEST_TIMEOUT_SECONDS))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        if (headers != null) {
            headers.forEach(builder::header);
        }
        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Provider returned HTTP " + response.statusCode() + ": " + response.body());
        }
        return MAPPER.readTree(response.body());
    }

    private JsonNode postJsonAllowError(String url, String body, Map<String, String> headers)
            throws InterruptedException {
        try {
            return postJson(url, body, headers);
        } catch (IOException e) {
            return null;
        }
    }

    private void consumeSse(String url, String body, Map<String, String> headers, Consumer<String> onDataLine)
            throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(REQUEST_TIMEOUT_SECONDS))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        if (headers != null) {
            headers.forEach(builder::header);
        }
        HttpResponse<Stream<String>> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofLines());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Provider returned HTTP " + response.statusCode() + " during streaming");
        }
        try (Stream<String> lines = response.body()) {
            for (String line : (Iterable<String>) lines::iterator) {
                if (line.startsWith("data:")) {
                    String data = line.substring(5).trim();
                    if (!data.isEmpty()) {
                        onDataLine.accept(data);
                    }
                }
            }
        }
    }

    private record ProviderCallResult(String answer, Usage usage, JsonNode structured,
                                        Boolean structuredValid, String structuredEnforcement,
                                        com.ragleap.rag.structured.ValidationMethod structuredValidationMethod) {
    }
}
