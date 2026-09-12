package com.ragleap.rag.embedding;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Constructor;
import java.util.Map;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class EmbeddingConfigTest {

    // Uses reflection to reach the package-private test constructor from
    // this same-package test class - no reflection tricks needed
    // actually, since the test class IS in the same package. Direct call.

    private static Function<String, String> fakeEnv(Map<String, String> vars) {
        return vars::get;
    }

    @Test
    void geminiResolvesFromExplicitArgsOverEnv() {
        EmbeddingConfig config = new EmbeddingConfig("gemini", "explicit-key", "gemini-embedding-001", 768, null,
                fakeEnv(Map.of("GEMINI_API_KEY", "env-key")));
        assertEquals("explicit-key", config.getApiKey());
        assertEquals("gemini-embedding-001", config.getModel());
        assertEquals(768, config.getDimensions());
    }

    @Test
    void geminiFallsBackToEnvironmentVariables() {
        EmbeddingConfig config = new EmbeddingConfig("gemini", null, null, null, null,
                fakeEnv(Map.of(
                        "GEMINI_API_KEY", "env-key",
                        "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001",
                        "EMBEDDING_DIMENSIONS", "3072"
                )));
        assertEquals("env-key", config.getApiKey());
        assertEquals("gemini-embedding-001", config.getModel());
        assertEquals(3072, config.getDimensions());
    }

    @Test
    void openAiCompatibleProviderGetsDefaultBaseUrl() {
        EmbeddingConfig config = new EmbeddingConfig("mistral", "key", "mistral-embed", 1024, null, fakeEnv(Map.of()));
        assertEquals("https://api.mistral.ai/v1", config.getBaseUrl());
    }

    @Test
    void openAiCompatibleProviderPerProviderEnvVarsOverrideGenericOnes() {
        EmbeddingConfig config = new EmbeddingConfig("together", null, null, null, null,
                fakeEnv(Map.of(
                        "TOGETHER_API_KEY", "tkey",
                        "TOGETHER_EMBEDDING_MODEL", "togethercomputer/m2-bert",
                        "TOGETHER_EMBEDDING_DIMENSIONS", "768",
                        "EMBEDDING_DIMENSIONS", "9999"
                )));
        assertEquals(768, config.getDimensions());
    }

    @Test
    void ollamaDoesNotRequireApiKey() {
        assertDoesNotThrow(() -> new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null, fakeEnv(Map.of())));
    }

    @Test
    void nonOllamaProviderWithoutApiKeyThrows() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingConfig("mistral", null, "mistral-embed", 1024, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("API key"));
    }

    @Test
    void missingModelThrows() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingConfig("ollama", null, null, 768, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("model"));
    }

    @Test
    void missingDimensionsThrows() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingConfig("ollama", null, "nomic-embed-text", null, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("dimensions"));
    }

    @Test
    void customProviderRequiresBaseUrl() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingConfig("custom", "key", "some-model", 512, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("base"));
    }

    @Test
    void customProviderWithExplicitBaseUrlWorks() {
        assertDoesNotThrow(() -> new EmbeddingConfig("custom", "key", "some-model", 512,
                "http://localhost:8080/v1", fakeEnv(Map.of())));
    }

    @Test
    void cohereAndVoyageAreCustomShapeProvidersWithNoBaseUrlAssigned() {
        EmbeddingConfig cohere = new EmbeddingConfig("cohere", "key", "embed-v3", 1024, null, fakeEnv(Map.of()));
        assertNull(cohere.getBaseUrl());
    }

    @Test
    void unknownProviderThrowsWithSupportedListInMessage() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> new EmbeddingConfig("not-a-real-provider", "key", "model", 100, null, fakeEnv(Map.of())));
        assertTrue(ex.getMessage().contains("Unknown embedding provider"));
        assertTrue(ex.getMessage().contains("gemini"));
    }

    @Test
    void providerNameIsCaseInsensitive() {
        EmbeddingConfig config = new EmbeddingConfig("GEMINI", "key", "model", 768, null, fakeEnv(Map.of()));
        assertEquals("gemini", config.getProvider());
    }

    @Test
    void publicConstructorUsesRealSystemGetenvWithoutThrowingOnConstruction() {
        // Sanity check the public (non-test) constructor path compiles and
        // runs against real System.getenv - using ollama since it's the
        // only provider that doesn't require an API key to succeed.
        assertDoesNotThrow(() -> new EmbeddingConfig("ollama", null, "nomic-embed-text", 768, null));
    }
}
