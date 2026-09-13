package com.ragleap.rag.generation;

import com.ragleap.rag.vectorstore.SearchResult;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.function.Function;

import static org.junit.jupiter.api.Assertions.*;

class GenerationServiceTest {

    private static ProviderConfig provider(String name) {
        return new ProviderConfig(name, "key", "some-model", null,
                (Function<String, String>) s -> null);
    }

    private static SearchResult chunk(String text, String docName, int chunkIndex, String docId, String chunkId) {
        return new SearchResult(chunkId, text, 0.9, docId, docName, chunkIndex);
    }

    // --- chain() ---

    @Test
    void chainReturnsOnlyOverrideWhenGiven() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(provider("anthropic")),
                0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);
        ProviderConfig override = provider("groq");

        List<ProviderConfig> result = service.chain(override);
        assertEquals(1, result.size());
        assertEquals("groq", result.get(0).getProvider());
    }

    @Test
    void chainReturnsPrimaryThenFallbacksWhenNoOverride() {
        GenerationService service = new GenerationService(provider("gemini"),
                List.of(provider("anthropic"), provider("groq")), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        List<ProviderConfig> result = service.chain(null);
        assertEquals(3, result.size());
        assertEquals("gemini", result.get(0).getProvider());
        assertEquals("anthropic", result.get(1).getProvider());
        assertEquals("groq", result.get(2).getProvider());
    }

    @Test
    void chainExcludesFallbackMatchingPrimaryProvider() {
        GenerationService service = new GenerationService(provider("gemini"),
                List.of(provider("gemini"), provider("anthropic")), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        List<ProviderConfig> result = service.chain(null);
        assertEquals(2, result.size());
        assertEquals("gemini", result.get(0).getProvider());
        assertEquals("anthropic", result.get(1).getProvider());
    }

    @Test
    void chainKeepsDuplicateFallbacksAmongThemselves() {
        // Matches the Python source exactly: fallbacks are only filtered
        // against primary, never against each other.
        GenerationService service = new GenerationService(provider("gemini"),
                List.of(provider("anthropic"), provider("anthropic")), 0.3, 1024, 12000, GenerationService.DEFAULT_SYSTEM_PROMPT);

        List<ProviderConfig> result = service.chain(null);
        assertEquals(3, result.size());
    }

    // --- trimChunksToBudget() ---

    @Test
    void trimChunksToBudgetKeepsAllWhenUnderBudget() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(), 0.3, 1024, 1000, GenerationService.DEFAULT_SYSTEM_PROMPT);
        List<SearchResult> chunks = List.of(chunk("short", "doc.txt", 0, "d1", "c1"));

        assertEquals(chunks, service.trimChunksToBudget(chunks));
    }

    @Test
    void trimChunksToBudgetAlwaysKeepsAtLeastFirstChunk() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(), 0.3, 1024, 5, GenerationService.DEFAULT_SYSTEM_PROMPT);
        // "a very long chunk text" is way over budget=5, but must still be kept alone
        List<SearchResult> chunks = List.of(chunk("a very long chunk text", "doc.txt", 0, "d1", "c1"));

        List<SearchResult> result = service.trimChunksToBudget(chunks);
        assertEquals(1, result.size());
    }

    @Test
    void trimChunksToBudgetStopsOnceOverBudgetAfterFirst() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(), 0.3, 1024, 10, GenerationService.DEFAULT_SYSTEM_PROMPT);
        List<SearchResult> chunks = List.of(
                chunk("12345", "doc.txt", 0, "d1", "c1"),   // 5 chars
                chunk("1234567", "doc.txt", 1, "d1", "c2"), // 7 chars, 5+7=12 > 10, drop
                chunk("1", "doc.txt", 2, "d1", "c3")        // never reached
        );

        List<SearchResult> result = service.trimChunksToBudget(chunks);
        assertEquals(1, result.size());
        assertEquals("12345", result.get(0).text());
    }

    @Test
    void trimChunksToBudgetDisabledWhenBudgetIsZeroOrNegative() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(), 0.3, 1024, 0, GenerationService.DEFAULT_SYSTEM_PROMPT);
        List<SearchResult> chunks = List.of(chunk("a".repeat(1000), "doc.txt", 0, "d1", "c1"));

        assertEquals(chunks, service.trimChunksToBudget(chunks));
    }

    @Test
    void trimChunksToBudgetHandlesEmptyList() {
        GenerationService service = new GenerationService(provider("gemini"), List.of(), 0.3, 1024, 100, GenerationService.DEFAULT_SYSTEM_PROMPT);
        assertEquals(List.of(), service.trimChunksToBudget(List.of()));
    }

    // --- buildContext() ---

    @Test
    void buildContextReturnsFallbackMessageForEmptyChunks() {
        GenerationService service = new GenerationService(provider("gemini"));
        assertEquals("No relevant context was found.", service.buildContext(List.of()));
    }

    @Test
    void buildContextFormatsSourceLabelsWithDocNameAndChunkIndex() {
        GenerationService service = new GenerationService(provider("gemini"));
        List<SearchResult> chunks = List.of(
                chunk("first chunk text", "report.pdf", 2, "d1", "c1"),
                chunk("second chunk text", "notes.txt", 5, "d1", "c2")
        );

        String context = service.buildContext(chunks);
        assertTrue(context.contains("[Source 1: report.pdf, chunk 2]\nfirst chunk text"));
        assertTrue(context.contains("[Source 2: notes.txt, chunk 5]\nsecond chunk text"));
    }

    // --- buildCitations() ---

    @Test
    void buildCitationsNumbersSequentiallyFromOne() {
        GenerationService service = new GenerationService(provider("gemini"));
        List<SearchResult> chunks = List.of(
                chunk("a", "doc1.txt", 0, "d1", "c1"),
                chunk("b", "doc2.txt", 1, "d2", "c2")
        );

        List<Citation> citations = service.buildCitations(chunks);
        assertEquals(1, citations.get(0).sourceNumber());
        assertEquals(2, citations.get(1).sourceNumber());
    }

    @Test
    void buildCitationsTruncatesLongTextTo150CharsWithEllipsis() {
        GenerationService service = new GenerationService(provider("gemini"));
        String longText = "x".repeat(200);
        List<SearchResult> chunks = List.of(chunk(longText, "doc.txt", 0, "d1", "c1"));

        Citation citation = service.buildCitations(chunks).get(0);
        assertEquals(153, citation.textPreview().length()); // 150 + "..."
        assertTrue(citation.textPreview().endsWith("..."));
    }

    @Test
    void buildCitationsDoesNotTruncateShortText() {
        GenerationService service = new GenerationService(provider("gemini"));
        List<SearchResult> chunks = List.of(chunk("short", "doc.txt", 0, "d1", "c1"));

        Citation citation = service.buildCitations(chunks).get(0);
        assertEquals("short", citation.textPreview());
        assertFalse(citation.textPreview().endsWith("..."));
    }

    // --- buildPrompt() ---

    @Test
    void buildPromptUsesDefaultSystemPromptWhenNoOverride() {
        GenerationService service = new GenerationService(provider("gemini"));
        String prompt = service.buildPrompt("what is X?", List.of(), null, "");

        assertTrue(prompt.startsWith(GenerationService.DEFAULT_SYSTEM_PROMPT));
        assertTrue(prompt.contains("Question: what is X?"));
        assertTrue(prompt.endsWith("Answer:"));
    }

    @Test
    void buildPromptUsesOverrideSystemPromptWhenGiven() {
        GenerationService service = new GenerationService(provider("gemini"));
        String prompt = service.buildPrompt("q", List.of(), "Custom instructions.", "");

        assertTrue(prompt.startsWith("Custom instructions."));
        assertFalse(prompt.contains(GenerationService.DEFAULT_SYSTEM_PROMPT));
    }

    @Test
    void buildPromptIncludesHistoryPrefixBeforeContext() {
        GenerationService service = new GenerationService(provider("gemini"));
        String prompt = service.buildPrompt("q", List.of(), null, "Previous turn: hi\n\n");

        int historyIdx = prompt.indexOf("Previous turn: hi");
        int contextIdx = prompt.indexOf("Context:");
        assertTrue(historyIdx >= 0 && historyIdx < contextIdx);
    }

    @Test
    void buildPromptIncludesNoRelevantContextMessageWhenChunksEmpty() {
        GenerationService service = new GenerationService(provider("gemini"));
        String prompt = service.buildPrompt("q", List.of(), null, "");
        assertTrue(prompt.contains("No relevant context was found."));
    }
}
