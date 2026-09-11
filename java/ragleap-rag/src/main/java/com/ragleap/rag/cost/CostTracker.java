package com.ragleap.rag.cost;

import java.util.HashMap;
import java.util.Map;

/**
 * Tracks cumulative spend and pricing table for a RagLeap instance.
 * Java port of ragleap-rag's cost.py — CostTracker.
 *
 * Not thread-safe by itself for the cumulative counter under heavy
 * concurrent use - acceptable for the common case (a single process
 * tracking its own approximate spend), not a precise multi-worker
 * ledger. For that, aggregate cost from on_answer hook events
 * externally instead (see com.ragleap.rag.observability.ObservabilityHooks).
 */
public class CostTracker {

    private final Map<String, Map<String, Rate>> pricingTable;
    private final Double budgetUsdPerMonth;
    private double cumulativeCostUsd = 0.0;

    public CostTracker() {
        this(null, null);
    }

    public CostTracker(Map<String, Map<String, Rate>> pricingTableOverride, Double budgetUsdPerMonth) {
        this.pricingTable = mergePricingTables(CostCalculator.SEED_PRICING_TABLE,
                pricingTableOverride != null ? pricingTableOverride : Map.of());
        this.budgetUsdPerMonth = budgetUsdPerMonth;
    }

    static Map<String, Map<String, Rate>> mergePricingTables(Map<String, Map<String, Rate>> base, Map<String, Map<String, Rate>> override) {
        Map<String, Map<String, Rate>> merged = new HashMap<>();
        for (Map.Entry<String, Map<String, Rate>> entry : base.entrySet()) {
            merged.put(entry.getKey(), new HashMap<>(entry.getValue()));
        }
        for (Map.Entry<String, Map<String, Rate>> entry : override.entrySet()) {
            Map<String, Rate> providerModels = merged.computeIfAbsent(entry.getKey(), k -> new HashMap<>());
            providerModels.putAll(entry.getValue());
        }
        return merged;
    }

    public Double record(String provider, String model, Map<String, Integer> usage) {
        Double cost = CostCalculator.computeCost(pricingTable, provider, model, usage);
        if (cost != null) {
            cumulativeCostUsd += cost;
        }
        return cost;
    }

    public boolean isOverBudget() {
        if (budgetUsdPerMonth == null) {
            return false;
        }
        return cumulativeCostUsd >= budgetUsdPerMonth;
    }

    public double getCumulativeCostUsd() {
        return cumulativeCostUsd;
    }

    public Map<String, Map<String, Rate>> getPricingTable() {
        return pricingTable;
    }
}
