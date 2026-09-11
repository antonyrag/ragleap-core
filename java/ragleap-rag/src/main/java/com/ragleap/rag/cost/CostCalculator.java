package com.ragleap.rag.cost;

import java.util.HashMap;
import java.util.Map;

/**
 * Cost tracking for ragleap-rag - computes real USD cost per ask() call
 * from actual provider-reported token usage. Java port of ragleap-rag's
 * cost.py (the stateless lookup/calculation half - see CostTracker for
 * the stateful cumulative-spend half).
 *
 * Honest limitation, same as the Python source: LLM API pricing changes
 * frequently. The seed table below covers only Gemini, Anthropic, and
 * OpenAI as verified on PRICING_TABLE_VERIFIED_DATE, and WILL go stale.
 * Pass an override table to CostTracker's constructor to keep costs
 * accurate - this is the expected, normal way to use it, not an edge
 * case. Unknown provider/model combinations return null rather than
 * guessing.
 */
public final class CostCalculator {

    private CostCalculator() {
    }

    public static final String PRICING_TABLE_VERIFIED_DATE = "2026-07-28";

    // USD per 1 million tokens. Verified against provider pricing pages/
    // documentation on PRICING_TABLE_VERIFIED_DATE above - see the
    // ragleap-rag README for sourcing notes. Ollama is $0 by design
    // (fully local inference, no per-token API cost).
    public static final Map<String, Map<String, Rate>> SEED_PRICING_TABLE = buildSeedTable();

    private static Map<String, Map<String, Rate>> buildSeedTable() {
        Map<String, Map<String, Rate>> table = new HashMap<>();

        Map<String, Rate> gemini = new HashMap<>();
        gemini.put("gemini-3.6-flash", new Rate(1.50, 7.50));
        gemini.put("gemini-3.1-pro", new Rate(2.00, 12.00));
        gemini.put("gemini-2.5-flash-lite", new Rate(0.10, 0.40));
        table.put("gemini", gemini);

        Map<String, Rate> anthropic = new HashMap<>();
        anthropic.put("claude-haiku-4-5-20251001", new Rate(1.00, 5.00));
        anthropic.put("claude-sonnet-5", new Rate(2.00, 10.00));
        anthropic.put("claude-opus-5", new Rate(5.00, 25.00));
        anthropic.put("claude-fable-5", new Rate(10.00, 50.00));
        table.put("anthropic", anthropic);

        Map<String, Rate> openai = new HashMap<>();
        openai.put("gpt-5.6-luna", new Rate(1.00, 6.00));
        openai.put("gpt-5.6-terra", new Rate(2.50, 15.00));
        openai.put("gpt-5.6-sol", new Rate(5.00, 30.00));
        table.put("openai", openai);

        Map<String, Rate> ollama = new HashMap<>();
        ollama.put("*", new Rate(0.0, 0.0)); // wildcard entry: any local model, $0
        table.put("ollama", ollama);

        return table;
    }

    static Rate lookupRate(Map<String, Map<String, Rate>> pricingTable, String provider, String model) {
        Map<String, Rate> providerTable = pricingTable.get(provider);
        if (providerTable == null || providerTable.isEmpty()) {
            return null;
        }
        if (model != null && providerTable.containsKey(model)) {
            return providerTable.get(model);
        }
        if (providerTable.containsKey("*")) { // wildcard entry, e.g. Ollama
            return providerTable.get("*");
        }
        return null;
    }

    /**
     * Return USD cost for this call, or null if the provider/model isn't
     * in the pricing table (never guesses) or usage data is unavailable.
     *
     * usage may be null OR empty - both mean "no usage data", matching
     * Python's `if not usage` truthiness check on an empty dict.
     */
    public static Double computeCost(Map<String, Map<String, Rate>> pricingTable, String provider, String model, Map<String, Integer> usage) {
        if (provider == null || usage == null || usage.isEmpty()) {
            return null;
        }
        Rate rate = lookupRate(pricingTable, provider, model);
        if (rate == null) {
            return null;
        }

        int promptTokens = usage.getOrDefault("prompt_tokens", 0);
        int completionTokens = usage.getOrDefault("completion_tokens", 0);

        double cost = (promptTokens / 1_000_000.0) * rate.input() + (completionTokens / 1_000_000.0) * rate.output();
        return Math.round(cost * 1_000_000.0) / 1_000_000.0; // round to 6 decimal places
    }
}
