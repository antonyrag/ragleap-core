package com.ragleap.rag.cost;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class CostCalculatorTest {

    @Test
    void computesKnownProviderModelCost() {
        // claude-sonnet-5: input $2.00/1M, output $10.00/1M
        Map<String, Integer> usage = Map.of("prompt_tokens", 1_000_000, "completion_tokens", 500_000);
        Double cost = CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "anthropic", "claude-sonnet-5", usage);
        assertNotNull(cost);
        assertEquals(2.00 + 5.00, cost, 0.000001);
    }

    @Test
    void unknownProviderReturnsNullNotZero() {
        Map<String, Integer> usage = Map.of("prompt_tokens", 100, "completion_tokens", 50);
        assertNull(CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "unknown-provider", "some-model", usage));
    }

    @Test
    void unknownModelWithNoWildcardReturnsNull() {
        Map<String, Integer> usage = Map.of("prompt_tokens", 100, "completion_tokens", 50);
        assertNull(CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "anthropic", "claude-nonexistent", usage));
    }

    @Test
    void ollamaWildcardMatchesAnyModel() {
        Map<String, Integer> usage = Map.of("prompt_tokens", 1_000_000, "completion_tokens", 1_000_000);
        Double cost = CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "ollama", "any-local-model-name", usage);
        assertNotNull(cost);
        assertEquals(0.0, cost);
    }

    @Test
    void nullProviderReturnsNull() {
        Map<String, Integer> usage = Map.of("prompt_tokens", 100, "completion_tokens", 50);
        assertNull(CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, null, "claude-sonnet-5", usage));
    }

    @Test
    void nullUsageReturnsNull() {
        assertNull(CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "anthropic", "claude-sonnet-5", null));
    }

    @Test
    void emptyUsageMapReturnsNull() {
        // Matches Python's `if not usage` - an empty dict is falsy too,
        // not just None/null.
        assertNull(CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "anthropic", "claude-sonnet-5", Map.of()));
    }

    @Test
    void missingTokenKeysDefaultToZero() {
        Double cost = CostCalculator.computeCost(CostCalculator.SEED_PRICING_TABLE, "anthropic", "claude-sonnet-5",
                Map.of("prompt_tokens", 1_000_000));
        assertEquals(2.00, cost, 0.000001);
    }
}
