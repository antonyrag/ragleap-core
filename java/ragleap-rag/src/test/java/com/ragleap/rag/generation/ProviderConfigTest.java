package com.ragleap.rag.generation;

import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class ProviderConfigTest {

    private static Function<String, String> fakeEnv(Map<String, String> vars) {
        return vars::get;
    }

    @Test
    void geminiResolvesFromExplicitArgsOverEnv() {
        ProviderConfig config = new ProviderConfig("gemini", "explicit-key", "gemini-2.5-flash", null,
                fakeEnv(Map.of("GEMINI_API_KEY", "env-key")));
        assertEquals("explicit-key", config.getApiKey());
        assertEquals("gemini-2.5-flash", config.getModel());
    }

    @Test
    void geminiFallsBackToEnvironmentVariables() {
        ProviderConfig config = new ProviderConfig("gemini", null, null, null,
                fakeEnv(Map.of("GEMINI_API_KEY", "env-key", "GEMINI_CHAT_MODEL", "gemini-2.5-flash")));
        assertEquals("env-key", config.getApiKey());
        assertEquals("gemini-2.5-flash", config.getModel());
    }

    @Test
    void anthropicResolvesFromEnv() {
        ProviderConfig config = new ProviderConfig("anthropic", null, null, null,
                fakeEnv(Map.of("ANTHROPIC_API_KEY", "key", "ANTHROPIC_MODEL", "claude-sonnet-5")));
        assertEquals("key", config.getApiKey());
        assertEquals("claude-sonnet-5", config.getModel());
    }

    @Test
    void openAiCompatibleProviderGetsDefaultBaseUrl() {
        ProviderConfig config = new ProviderConfig("groq", "key", "llama-3.3-70b", null, fakeEnv(Map.of()));
        assertEquals("https://api.groq.com/openai/v1", config.getBaseUrl());
    }

    @Test
    void ollamaDoesNotRequireApiKey() {
        assertDoesNotThrow(() -> new ProviderConfig("ollama", null, "qwen2.5:0.5b", null, fakeEnv(Map.of())));
    }

    @Test
    void nonOllamaProviderWithoutApiKeyThrows() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new ProviderConfig("groq", null, "model", null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("API key"));
    }

    @Test
    void namedProviderMissingModelThrowsDetailedMessage() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new ProviderConfig("gemini", "key", null, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("GEMINI_CHAT_MODEL"));
        assertTrue(ex.getMessage().contains("never hardcodes a default model"));
    }

    @Test
    void customProviderMissingModelThrowsGenericMessage() {
        // Exercises the second (generic) check - custom is deliberately
        // exempted from the first (detailed) check but still requires a
        // model via the second check, per the Python source's structure.
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new ProviderConfig("custom", "key", null, "http://localhost:8080/v1", fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("No model for provider 'custom'"));
        assertFalse(ex.getMessage().contains("never hardcodes"));
    }

    @Test
    void customProviderRequiresBaseUrl() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new ProviderConfig("custom", "key", "some-model", null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("baseUrl"));
    }

    @Test
    void customProviderWithModelAndBaseUrlWorks() {
        assertDoesNotThrow(() -> new ProviderConfig("custom", "key", "some-model",
                "http://localhost:8080/v1", fakeEnv(Map.of())));
    }

    @Test
    void geminiAndAnthropicDoNotRequireBaseUrl() {
        assertDoesNotThrow(() -> new ProviderConfig("gemini", "key", "gemini-2.5-flash", null, fakeEnv(Map.of())));
        assertDoesNotThrow(() -> new ProviderConfig("anthropic", "key", "claude-sonnet-5", null, fakeEnv(Map.of())));
    }

    @Test
    void unknownProviderThrowsWithSupportedListInMessage() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new ProviderConfig("not-a-real-provider", "key", "model", null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("Unknown provider"));
        assertTrue(ex.getMessage().contains("gemini"));
        assertTrue(ex.getMessage().contains("anthropic"));
    }

    @Test
    void providerNameIsCaseInsensitive() {
        ProviderConfig config = new ProviderConfig("GEMINI", "key", "model", null, fakeEnv(Map.of()));
        assertEquals("gemini", config.getProvider());
    }

    @Test
    void publicConstructorUsesRealSystemGetenvWithoutThrowingOnConstruction() {
        assertDoesNotThrow(() -> new ProviderConfig("ollama", null, "qwen2.5:0.5b", null));
    }
}
