package com.ragleap.rag.embedding;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Generates vector embeddings using the configured provider. Java port
 * of ragleap-rag's embedding.py — EmbeddingService.
 *
 * Uses java.net.http.HttpClient (built into the JDK since 11) rather
 * than adding a provider-specific SDK dependency for each provider -
 * every provider here is a simple JSON-over-HTTPS POST, the same
 * approach the Python source already uses directly for cohere/voyage
 * via requests, extended here to cover openai-compatible and gemini
 * too rather than mixing in separate client libraries.
 *
 * Live-verification status, same honesty standard as the Python
 * source: ollama is live-verified in this Java port (local, no API
 * key, via nomic-embed-text, against the real Ollama instance on this
 * VPS). gemini, openai, mistral, together, cohere, and voyage are
 * code-complete per each provider's public API documentation but NOT
 * live-verified in Java - no paid API keys available to test against.
 * Treat their request/response shapes as best-effort until confirmed
 * live, exactly the same caveat the Python source attaches to its own
 * untested providers.
 */
public class EmbeddingService {

    private static final Logger logger = Logger.getLogger(EmbeddingService.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final EmbeddingConfig config;
    private final HttpClient httpClient;

    // Overridable only via the package-private test constructor - lets
    // tests point gemini/cohere/voyage at a local stub server instead of
    // their real hardcoded hosts, the same way EmbeddingConfig's env
    // injection lets tests avoid real System.getenv().
    private final String geminiBaseUrl;
    private final String cohereBaseUrl;
    private final String voyageBaseUrl;

    public EmbeddingService(EmbeddingConfig config) {
        this(config, HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(30)).build(),
                "https://generativelanguage.googleapis.com",
                "https://api.cohere.ai",
                "https://api.voyageai.com");
    }

    EmbeddingService(EmbeddingConfig config, HttpClient httpClient,
                      String geminiBaseUrl, String cohereBaseUrl, String voyageBaseUrl) {
        this.config = config;
        this.httpClient = httpClient;
        this.geminiBaseUrl = geminiBaseUrl;
        this.cohereBaseUrl = cohereBaseUrl;
        this.voyageBaseUrl = voyageBaseUrl;
    }

    public String getModel() {
        return config.getModel();
    }

    public Integer getDimensions() {
        return config.getDimensions();
    }

    /** Generate an embedding vector for a single piece of text. */
    public List<Double> embedText(String text) {
        if (text == null || text.isBlank()) {
            logger.warning("Empty text provided for embedding");
            return null;
        }
        try {
            return switch (config.getProvider()) {
                case "gemini" -> embedGemini(text);
                case "cohere" -> embedCohere(List.of(text)).get(0);
                case "voyage" -> embedVoyage(List.of(text)).get(0);
                default -> embedOpenAiCompatible(text);
            };
        } catch (Exception e) {
            logger.severe("Embedding generation failed (" + config.getProvider() + "): " + e);
            return null;
        }
    }

    /** Generate embeddings for multiple texts. */
    public List<List<Double>> embedBatch(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return List.of();
        }
        try {
            return switch (config.getProvider()) {
                case "gemini" -> embedBatchGemini(texts);
                case "cohere" -> embedCohere(texts);
                case "voyage" -> embedVoyage(texts);
                default -> embedBatchOpenAiCompatible(texts);
            };
        } catch (Exception e) {
            logger.severe("Batch embedding generation failed (" + config.getProvider() + "): " + e);
            List<List<Double>> nulls = new ArrayList<>();
            for (int i = 0; i < texts.size(); i++) {
                nulls.add(null);
            }
            return nulls;
        }
    }

    // --- gemini ---

    private List<Double> embedGemini(String text) throws IOException, InterruptedException {
        String url = geminiBaseUrl + "/v1beta/models/" + config.getModel()
                + ":embedContent?key=" + config.getApiKey();

        ObjectNode body = MAPPER.createObjectNode();
        ObjectNode content = body.putObject("content");
        content.putArray("parts").addObject().put("text", text);

        JsonNode response = postJson(url, body, null);
        return toDoubleList(response.path("embedding").path("values"));
    }

    private List<List<Double>> embedBatchGemini(List<String> texts) throws IOException, InterruptedException {
        String url = geminiBaseUrl + "/v1beta/models/" + config.getModel()
                + ":batchEmbedContents?key=" + config.getApiKey();

        ObjectNode body = MAPPER.createObjectNode();
        ArrayNode requests = body.putArray("requests");
        for (String text : texts) {
            ObjectNode req = requests.addObject();
            req.put("model", "models/" + config.getModel());
            ObjectNode content = req.putObject("content");
            content.putArray("parts").addObject().put("text", text);
        }

        JsonNode response = postJson(url, body, null);
        List<List<Double>> results = new ArrayList<>();
        for (JsonNode embedding : response.path("embeddings")) {
            results.add(toDoubleList(embedding.path("values")));
        }
        return results;
    }

    // --- openai-compatible: openai, mistral, together, ollama, custom ---

    private List<Double> embedOpenAiCompatible(String text) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("model", config.getModel());
        body.put("input", text);
        if (config.getProvider().equals("openai") && config.getDimensions() != null) {
            body.put("dimensions", config.getDimensions());
        }

        JsonNode response = postJson(config.getBaseUrl() + "/embeddings", body, config.getApiKey());
        return toDoubleList(response.path("data").get(0).path("embedding"));
    }

    private List<List<Double>> embedBatchOpenAiCompatible(List<String> texts) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("model", config.getModel());
        ArrayNode input = body.putArray("input");
        texts.forEach(input::add);
        if (config.getProvider().equals("openai") && config.getDimensions() != null) {
            body.put("dimensions", config.getDimensions());
        }

        JsonNode response = postJson(config.getBaseUrl() + "/embeddings", body, config.getApiKey());
        List<List<Double>> results = new ArrayList<>();
        for (JsonNode d : response.path("data")) {
            results.add(toDoubleList(d.path("embedding")));
        }
        return results;
    }

    // --- cohere: NOT live-verified, per public API docs ---

    /**
     * Always uses input_type='search_document' since embedText()/
     * embedBatch() don't currently distinguish query vs. document
     * embedding calls - a known limitation, matching the Python
     * source exactly.
     */
    private List<List<Double>> embedCohere(List<String> texts) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        ArrayNode textsNode = body.putArray("texts");
        texts.forEach(textsNode::add);
        body.put("model", config.getModel());
        body.put("input_type", "search_document");

        JsonNode response = postJson(cohereBaseUrl + "/v1/embed", body, config.getApiKey());
        List<List<Double>> results = new ArrayList<>();
        for (JsonNode embedding : response.path("embeddings")) {
            results.add(toDoubleList(embedding));
        }
        return results;
    }

    // --- voyage: NOT live-verified, per public API docs ---

    private List<List<Double>> embedVoyage(List<String> texts) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        ArrayNode input = body.putArray("input");
        texts.forEach(input::add);
        body.put("model", config.getModel());

        JsonNode response = postJson(voyageBaseUrl + "/v1/embeddings", body, config.getApiKey());
        List<List<Double>> results = new ArrayList<>();
        for (JsonNode d : response.path("data")) {
            results.add(toDoubleList(d.path("embedding")));
        }
        return results;
    }

    // --- shared HTTP helper ---

    private JsonNode postJson(String url, ObjectNode body, String bearerToken) throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .timeout(Duration.ofSeconds(30))
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()));

        if (bearerToken != null) {
            builder.header("Authorization", "Bearer " + bearerToken);
        }

        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 400) {
            throw new IOException("HTTP " + response.statusCode() + " from " + url + ": " + response.body());
        }
        return MAPPER.readTree(response.body());
    }

    private static List<Double> toDoubleList(JsonNode arrayNode) {
        List<Double> values = new ArrayList<>();
        for (JsonNode v : arrayNode) {
            values.add(v.asDouble());
        }
        return values;
    }
}
