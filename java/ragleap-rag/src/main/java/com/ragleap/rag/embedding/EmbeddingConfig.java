package com.ragleap.rag.embedding;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Explicit embedding provider configuration for ragleap-rag. Java port
 * of ragleap-rag's embedding.py — EmbeddingConfig.
 *
 * No model or dimensions value is ever hardcoded as a silent default -
 * provider model names, availability, and dimensions all change over
 * time, so this always requires you to know and specify both, one way
 * or another (constructor arg or environment variable) - matching the
 * Python source's documented reasoning exactly.
 */
public final class EmbeddingConfig {

    // Providers whose embeddings endpoint is OpenAI-compatible (same
    // request/response shape as OpenAI's /v1/embeddings).
    public static final Map<String, String> OPENAI_COMPATIBLE_BASE_URLS = buildOpenAiCompatibleBaseUrls();

    private static Map<String, String> buildOpenAiCompatibleBaseUrls() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("openai", "https://api.openai.com/v1");
        m.put("mistral", "https://api.mistral.ai/v1");
        m.put("together", "https://api.together.xyz/v1");
        m.put("ollama", "http://localhost:11434/v1");
        return Map.copyOf(m);
    }

    // Providers with their own (non-OpenAI-compatible) response shape.
    public static final Set<String> CUSTOM_SHAPE_PROVIDERS = Set.of("cohere", "voyage");

    private static final List<String> ALL_PROVIDERS = buildAllProviders();

    private static List<String> buildAllProviders() {
        List<String> all = new java.util.ArrayList<>();
        all.add("gemini");
        all.addAll(OPENAI_COMPATIBLE_BASE_URLS.keySet());
        all.addAll(CUSTOM_SHAPE_PROVIDERS);
        all.add("custom");
        return List.copyOf(all);
    }

    private final String provider;
    private final String apiKey;
    private final String model;
    private final Integer dimensions;
    private final String baseUrl;

    public EmbeddingConfig(String provider, String apiKey, String model, Integer dimensions, String baseUrl) {
        this(provider, apiKey, model, dimensions, baseUrl, System::getenv);
    }

    /**
     * Package-private constructor allowing tests to inject a fake
     * environment lookup instead of real System.getenv() - the Java
     * equivalent of monkeypatching os.environ in the Python tests.
     */
    EmbeddingConfig(String provider, String apiKey, String model, Integer dimensions, String baseUrl,
                     Function<String, String> env) {
        String resolvedProvider = provider.toLowerCase();
        String resolvedApiKey = apiKey;
        String resolvedModel = model;
        Integer resolvedDimensions = dimensions;
        String resolvedBaseUrl = baseUrl;

        if (resolvedProvider.equals("gemini")) {
            resolvedApiKey = firstNonNull(resolvedApiKey, env.apply("GEMINI_API_KEY"));
            resolvedModel = firstNonNull(resolvedModel, env.apply("GEMINI_EMBEDDING_MODEL"));
            resolvedDimensions = firstNonNull(resolvedDimensions, parseIntOrNull(env.apply("EMBEDDING_DIMENSIONS")));
        } else if (OPENAI_COMPATIBLE_BASE_URLS.containsKey(resolvedProvider)) {
            String upper = resolvedProvider.toUpperCase();
            resolvedApiKey = firstNonNull(resolvedApiKey, env.apply(upper + "_API_KEY"));
            resolvedModel = firstNonNull(resolvedModel, env.apply(upper + "_EMBEDDING_MODEL"));
            String envDims = firstNonNull(env.apply(upper + "_EMBEDDING_DIMENSIONS"), env.apply("EMBEDDING_DIMENSIONS"));
            resolvedDimensions = firstNonNull(resolvedDimensions, parseIntOrNull(envDims));
            resolvedBaseUrl = firstNonNull(resolvedBaseUrl, OPENAI_COMPATIBLE_BASE_URLS.get(resolvedProvider));
        } else if (CUSTOM_SHAPE_PROVIDERS.contains(resolvedProvider)) {
            String upper = resolvedProvider.toUpperCase();
            resolvedApiKey = firstNonNull(resolvedApiKey, env.apply(upper + "_API_KEY"));
            resolvedModel = firstNonNull(resolvedModel, env.apply(upper + "_EMBEDDING_MODEL"));
            String envDims = firstNonNull(env.apply(upper + "_EMBEDDING_DIMENSIONS"), env.apply("EMBEDDING_DIMENSIONS"));
            resolvedDimensions = firstNonNull(resolvedDimensions, parseIntOrNull(envDims));
        } else if (resolvedProvider.equals("custom")) {
            resolvedApiKey = firstNonNull(resolvedApiKey, env.apply("CUSTOM_EMBEDDING_API_KEY"));
            resolvedModel = firstNonNull(resolvedModel, env.apply("CUSTOM_EMBEDDING_MODEL"));
            String envDims = firstNonNull(env.apply("CUSTOM_EMBEDDING_DIMENSIONS"), env.apply("EMBEDDING_DIMENSIONS"));
            resolvedDimensions = firstNonNull(resolvedDimensions, parseIntOrNull(envDims));
            resolvedBaseUrl = firstNonNull(resolvedBaseUrl, env.apply("CUSTOM_EMBEDDING_BASE_URL"));
            if (resolvedBaseUrl == null) {
                throw new IllegalArgumentException(
                        "No baseUrl for provider 'custom'. Pass baseUrl explicitly to EmbeddingConfig(), " +
                        "or set CUSTOM_EMBEDDING_BASE_URL in your environment - it must point to an " +
                        "OpenAI-compatible /embeddings endpoint.");
            }
        } else {
            throw new IllegalArgumentException(
                    "Unknown embedding provider '" + resolvedProvider + "'. Supported: " +
                    String.join(", ", ALL_PROVIDERS) + ".");
        }

        if (resolvedApiKey == null && !resolvedProvider.equals("ollama")) {
            throw new IllegalArgumentException(
                    "No API key for embedding provider '" + resolvedProvider + "'. Pass apiKey explicitly " +
                    "to EmbeddingConfig(), or set " + resolvedProvider.toUpperCase() + "_API_KEY in your environment.");
        }
        if (resolvedModel == null) {
            throw new IllegalArgumentException(
                    "No embedding model specified for provider '" + resolvedProvider + "'. Pass model " +
                    "explicitly to EmbeddingConfig(), or set " + resolvedProvider.toUpperCase() +
                    "_EMBEDDING_MODEL in your environment. ragleap-rag never hardcodes a default embedding " +
                    "model - provider model availability and dimensions change too frequently for a baked-in " +
                    "default to stay reliable.");
        }
        if (resolvedDimensions == null) {
            throw new IllegalArgumentException(
                    "No dimensions specified for embedding provider '" + resolvedProvider + "' model '" +
                    resolvedModel + "'. Pass dimensions explicitly to EmbeddingConfig(), or set " +
                    "EMBEDDING_DIMENSIONS (or " + resolvedProvider.toUpperCase() + "_EMBEDDING_DIMENSIONS) " +
                    "in your environment - dimensions must match your chosen model exactly, and ragleap-rag " +
                    "can't safely guess it.");
        }

        this.provider = resolvedProvider;
        this.apiKey = resolvedApiKey;
        this.model = resolvedModel;
        this.dimensions = resolvedDimensions;
        this.baseUrl = resolvedBaseUrl;
    }

    private static String firstNonNull(String a, String b) {
        return a != null ? a : b;
    }

    private static Integer firstNonNull(Integer a, Integer b) {
        return a != null ? a : b;
    }

    private static Integer parseIntOrNull(String s) {
        if (s == null || s.isEmpty()) {
            return null;
        }
        return Integer.parseInt(s);
    }

    public String getProvider() {
        return provider;
    }

    public String getApiKey() {
        return apiKey;
    }

    public String getModel() {
        return model;
    }

    public Integer getDimensions() {
        return dimensions;
    }

    public String getBaseUrl() {
        return baseUrl;
    }
}
