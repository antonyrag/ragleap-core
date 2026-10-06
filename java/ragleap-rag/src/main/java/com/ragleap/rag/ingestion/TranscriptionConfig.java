package com.ragleap.rag.ingestion;

import java.net.URI;
import java.util.Locale;
import java.util.Objects;
import java.util.function.Function;

/**
 * Explicit transcription provider configuration. Java port of ragleap-rag's transcription.py
 * (TranscriptionConfig). provider "whisper" (OpenAI's hosted API) and "deepgram" are built in; any other provider
 * uses provider "custom" with a {@link TranscribeFunction}.
 *
 * <p>Defaults follow the Python class: whisper uses model "whisper-1" and the OPENAI_API_KEY environment
 * variable, deepgram uses "nova-2" and DEEPGRAM_API_KEY, an empty explicit key falls back to the environment, and
 * a missing key is an error. {@link #withBaseUrl(String)} is a Java-only addition for OpenAI-compatible servers and
 * tests; the API key is sent to that URL, so only use a service you trust.
 */
public final class TranscriptionConfig {

    public static final String DEFAULT_WHISPER_BASE_URL = "https://api.openai.com/v1";
    public static final String DEFAULT_DEEPGRAM_BASE_URL = "https://api.deepgram.com";

    private final String provider;
    private final String apiKey;
    private final String model;
    private final String language;
    private final String prompt;
    private final TranscribeFunction transcribeFn;
    private final String baseUrl;

    public TranscriptionConfig(String provider, String apiKey, String model, String language, String prompt,
                               TranscribeFunction transcribeFn) {
        this(provider, apiKey, model, language, prompt, transcribeFn, null, System::getenv);
    }

    /** Package-private so tests can inject a fake environment lookup. */
    TranscriptionConfig(String provider, String apiKey, String model, String language, String prompt,
                        TranscribeFunction transcribeFn, String baseUrl, Function<String, String> env) {
        String p = Objects.requireNonNull(provider, "provider").toLowerCase(Locale.ROOT);
        String key = apiKey;
        String resolvedModel = model;
        String keyVariable = null;
        switch (p) {
            case "whisper" -> {
                key = firstNonEmpty(key, env.apply("OPENAI_API_KEY"));
                resolvedModel = firstNonEmpty(resolvedModel, "whisper-1");
                keyVariable = "OPENAI_API_KEY";
            }
            case "deepgram" -> {
                key = firstNonEmpty(key, env.apply("DEEPGRAM_API_KEY"));
                resolvedModel = firstNonEmpty(resolvedModel, "nova-2");
                keyVariable = "DEEPGRAM_API_KEY";
            }
            case "custom" -> {
                if (transcribeFn == null) {
                    throw new IllegalArgumentException(
                            "provider='custom' requires a TranscribeFunction: (filename, audioBytes) -> transcript.");
                }
            }
            default -> throw new IllegalArgumentException(
                    "Unknown transcription provider '" + p + "'. Supported: whisper, deepgram, custom.");
        }
        if (keyVariable != null && (key == null || key.isEmpty())) {
            throw new IllegalArgumentException("No API key for transcription provider '" + p
                    + "'. Pass apiKey explicitly, or set " + keyVariable + " in your environment.");
        }
        this.provider = p;
        this.apiKey = key;
        this.model = resolvedModel;
        this.language = language;
        this.prompt = prompt;
        this.transcribeFn = transcribeFn;
        this.baseUrl = normalizeBaseUrl(baseUrl);
    }

    private TranscriptionConfig(TranscriptionConfig other, String baseUrl) {
        this.provider = other.provider;
        this.apiKey = other.apiKey;
        this.model = other.model;
        this.language = other.language;
        this.prompt = other.prompt;
        this.transcribeFn = other.transcribeFn;
        this.baseUrl = baseUrl;
    }

    /** A copy of this configuration that sends requests to another base URL (http or https). */
    public TranscriptionConfig withBaseUrl(String newBaseUrl) {
        return new TranscriptionConfig(this, normalizeBaseUrl(Objects.requireNonNull(newBaseUrl, "newBaseUrl")));
    }

    public String provider() {
        return provider;
    }

    public String model() {
        return model;
    }

    public String language() {
        return language;
    }

    public String prompt() {
        return prompt;
    }

    String apiKey() {
        return apiKey;
    }

    TranscribeFunction transcribeFn() {
        return transcribeFn;
    }

    /** The base URL requests go to: the configured one, else the provider's public API. */
    String effectiveBaseUrl() {
        if (baseUrl != null) {
            return baseUrl;
        }
        return provider.equals("deepgram") ? DEFAULT_DEEPGRAM_BASE_URL : DEFAULT_WHISPER_BASE_URL;
    }

    @Override
    public String toString() {
        return "TranscriptionConfig{provider=" + provider + ", model=" + model + ", language=" + language
                + ", apiKey=" + (apiKey == null || apiKey.isEmpty() ? "none" : "***") + "}";
    }

    private static String firstNonEmpty(String a, String b) {
        return a != null && !a.isEmpty() ? a : b;
    }

    private static String normalizeBaseUrl(String url) {
        if (url == null) {
            return null;
        }
        String s = url.strip();
        URI uri;
        try {
            uri = URI.create(s);
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("baseUrl is not a valid URL: " + url, e);
        }
        String scheme = uri.getScheme();
        boolean httpScheme = scheme != null && (scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"));
        if (!httpScheme || uri.getHost() == null) {
            throw new IllegalArgumentException("baseUrl must be an http or https URL with a host: " + url);
        }
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        return s;
    }
}
