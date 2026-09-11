package com.ragleap.rag.cost;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class CostTrackerTest {

    @Test
    void recordReturnsAndAccumulatesCost() {
        CostTracker tracker = new CostTracker();
        Double cost1 = tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0));
        Double cost2 = tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0));

        assertEquals(2.00, cost1, 0.000001);
        assertEquals(2.00, cost2, 0.000001);
        assertEquals(4.00, tracker.getCumulativeCostUsd(), 0.000001);
    }

    @Test
    void unrecordableCallDoesNotAffectCumulative() {
        CostTracker tracker = new CostTracker();
        Double cost = tracker.record("unknown-provider", "model", Map.of("prompt_tokens", 100, "completion_tokens", 50));

        assertNull(cost);
        assertEquals(0.0, tracker.getCumulativeCostUsd());
    }

    @Test
    void isOverBudgetFalseWhenNoBudgetSet() {
        CostTracker tracker = new CostTracker();
        tracker.record("anthropic", "claude-opus-5", Map.of("prompt_tokens", 10_000_000, "completion_tokens", 10_000_000));
        assertFalse(tracker.isOverBudget());
    }

    @Test
    void isOverBudgetTrueWhenCumulativeMeetsOrExceedsBudget() {
        CostTracker tracker = new CostTracker(null, 1.00);
        tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0)); // $2.00

        assertTrue(tracker.isOverBudget());
    }

    @Test
    void isOverBudgetFalseWhenBelowBudget() {
        CostTracker tracker = new CostTracker(null, 100.00);
        tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0)); // $2.00

        assertFalse(tracker.isOverBudget());
    }

    @Test
    void overrideTableAddsNewModelWithoutRemovingSeedModels() {
        Map<String, Map<String, Rate>> override = Map.of(
                "anthropic", Map.of("claude-future-model", new Rate(3.00, 15.00))
        );
        CostTracker tracker = new CostTracker(override, null);

        Double newModelCost = tracker.record("anthropic", "claude-future-model", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0));
        Double existingModelCost = tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 0));

        assertEquals(3.00, newModelCost, 0.000001);
        assertEquals(2.00, existingModelCost, 0.000001); // seed model still present
    }

    @Test
    void overrideTableCanReplaceExistingRate() {
        Map<String, Map<String, Rate>> override = Map.of(
                "anthropic", Map.of("claude-sonnet-5", new Rate(1.00, 1.00))
        );
        CostTracker tracker = new CostTracker(override, null);

        Double cost = tracker.record("anthropic", "claude-sonnet-5", Map.of("prompt_tokens", 1_000_000, "completion_tokens", 1_000_000));
        assertEquals(2.00, cost, 0.000001); // 1.00 input + 1.00 output, not the seed 2.00+10.00
    }

    @Test
    void seedPricingTableUnaffectedByTrackerInstances() {
        // The merge must not mutate CostCalculator.SEED_PRICING_TABLE itself
        new CostTracker(Map.of("anthropic", Map.of("claude-sonnet-5", new Rate(999.0, 999.0))), null);

        Rate seedRate = CostCalculator.SEED_PRICING_TABLE.get("anthropic").get("claude-sonnet-5");
        assertEquals(2.00, seedRate.input());
        assertEquals(10.00, seedRate.output());
    }
}
