package com.ragleap.rag.generation;

import com.ragleap.rag.vectorstore.SearchResult;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Generates a grounded answer using the configured provider, with an
 * optional fallback chain, streaming, and real token usage reporting.
 * Java port of ragleap-rag's generation.py - GenerationService.
 *
 * This is the pure-logic half only: the fallback chain, context/prompt
 * building, chunk trimming, and citation building - none of which make
 * a network call. The actual provider calls (generateAnswer,
 * generateAnswerStream, non-streaming and streaming across gemini/
 * anthropic/openai-compatible shapes) are a deliberate follow-up PR.
 *
 * Chunks are represented as com.ragleap.rag.vectorstore.SearchResult
 * rather than a duplicate shape - its fields (text, documentName,
 * chunkIndex, documentId, chunkId) already match exactly what the
 * Python source's chunk dicts carry into this class.
 */
public class GenerationService {

    private static final Logger logger = Logger.getLogger(GenerationService.class.getName());

    public static final String DEFAULT_SYSTEM_PROMPT =
            "You are a helpful assistant that answers questions using ONLY the provided context.\n" +
            "If the answer is not in the context, say clearly that you don't have that information — do not make things up.\n" +
            "Always be concise and cite which document your answer came from when possible.";

    private final ProviderConfig primary;
    private final List<ProviderConfig> fallbacks;
    private final double defaultTemperature;
    private final int defaultMaxTokens;
    private final int maxContextChars;
    private final String systemPrompt;

    public GenerationService(ProviderConfig primary) {
        this(primary, List.of(), 0.3, 1024, 12000, DEFAULT_SYSTEM_PROMPT);
    }

    public GenerationService(ProviderConfig primary, List<ProviderConfig> fallbacks,
                               double defaultTemperature, int defaultMaxTokens,
                               int maxContextChars, String systemPrompt) {
        this.primary = primary;
        this.fallbacks = fallbacks != null ? fallbacks : List.of();
        this.defaultTemperature = defaultTemperature;
        this.defaultMaxTokens = defaultMaxTokens;
        this.maxContextChars = maxContextChars;
        this.systemPrompt = systemPrompt;
    }

    public ProviderConfig getPrimary() {
        return primary;
    }

    public List<ProviderConfig> getFallbacks() {
        return fallbacks;
    }

    public double getDefaultTemperature() {
        return defaultTemperature;
    }

    public int getDefaultMaxTokens() {
        return defaultMaxTokens;
    }

    public int getMaxContextChars() {
        return maxContextChars;
    }

    public String getSystemPrompt() {
        return systemPrompt;
    }

    /**
     * The ordered list of providers to try. If overrideProvider is
     * given, it's the only entry - otherwise it's primary followed by
     * every fallback whose provider name differs from primary's.
     * Matches the Python source exactly: this filters fallbacks against
     * primary only, not against each other - two fallbacks with the
     * same provider name both stay in the chain.
     */
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

    /**
     * Trims the chunk list to fit within maxContextChars, keeping
     * chunks in order and always keeping at least the first one even
     * if it alone exceeds the budget (matches the Python source's
     * "&& kept" guard - the break only fires once something is
     * already kept).
     */
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

    /** Builds the numbered [Source N: ...] context block sent to the model. */
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

    /**
     * Structured citation list mapping each [Source N] label used in
     * the prompt to the specific chunk it refers to.
     */
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

    /** Assembles the full prompt sent to the model: instructions, history, context, question. */
    String buildPrompt(String query, List<SearchResult> chunks, String systemPromptOverride, String historyPrefix) {
        String context = buildContext(chunks);
        String instructions = systemPromptOverride != null ? systemPromptOverride : this.systemPrompt;
        String prefix = historyPrefix != null ? historyPrefix : "";
        return instructions + "\n\n" + prefix + "Context:\n" + context + "\n\nQuestion: " + query + "\nAnswer:";
    }
}
