"""
Cost tracking for ragleap-rag - computes real USD cost per ask() call
from actual provider-reported token usage, and optionally tracks
cumulative spend against a budget to trigger fallback to a cheaper
provider.

Honest limitation: LLM API pricing changes frequently - three major
providers each shipped new model pricing tiers within the same week
during this table's creation (verified 2026-07-28). The seed table
below covers only Gemini, Anthropic, and OpenAI, and WILL go stale.
Pass pricing_table= to RagLeap() to override or extend it - this is
the expected, normal way to keep costs accurate, not an edge case.
Unknown provider/model combinations return cost_usd=None rather than
guessing.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PRICING_TABLE_VERIFIED_DATE = "2026-07-28"

# USD per 1 million tokens. Verified against provider pricing pages/
# documentation on PRICING_TABLE_VERIFIED_DATE above - see the
# ragleap-rag README for sourcing notes. Ollama is $0 by design
# (fully local inference, no per-token API cost).
SEED_PRICING_TABLE: Dict[str, Dict[str, Dict[str, float]]] = {
    "gemini": {
        "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
        "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
        "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    },
    "anthropic": {
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00},
        "claude-opus-5": {"input": 5.00, "output": 25.00},
        "claude-fable-5": {"input": 10.00, "output": 50.00},
    },
    "openai": {
        "gpt-5.6-luna": {"input": 1.00, "output": 6.00},
        "gpt-5.6-terra": {"input": 2.50, "output": 15.00},
        "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
    },
    "ollama": {
        "*": {"input": 0.0, "output": 0.0},
    },
}


def _lookup_rate(pricing_table: Dict, provider: str, model: Optional[str]) -> Optional[Dict[str, float]]:
    provider_table = pricing_table.get(provider)
    if not provider_table:
        return None
    if model and model in provider_table:
        return provider_table[model]
    if "*" in provider_table:  # wildcard entry, e.g. Ollama (any local model, $0)
        return provider_table["*"]
    return None


def compute_cost(pricing_table: Dict, provider: Optional[str], model: Optional[str], usage: Optional[Dict]) -> Optional[float]:
    """
    Return USD cost for this call, or None if the provider/model isn't
    in the pricing table (never guesses) or usage data is unavailable.
    """
    if not provider or not usage:
        return None
    rate = _lookup_rate(pricing_table, provider, model)
    if rate is None:
        return None

    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0

    cost = (prompt_tokens / 1_000_000) * rate["input"] + (completion_tokens / 1_000_000) * rate["output"]
    return round(cost, 6)


class CostTracker:
    """Tracks cumulative spend and pricing table for a RagLeap instance.
    Not thread-safe by itself for the cumulative counter under heavy
    concurrent use - acceptable for the common case (a single process
    tracking its own approximate spend), not a precise multi-worker
    ledger. For that, aggregate cost_usd from on_answer hook events
    externally instead."""

    def __init__(self, pricing_table: Optional[Dict] = None, budget_usd_per_month: Optional[float] = None):
        self.pricing_table = self._merge_pricing_tables(SEED_PRICING_TABLE, pricing_table or {})
        self.budget_usd_per_month = budget_usd_per_month
        self.cumulative_cost_usd = 0.0

    @staticmethod
    def _merge_pricing_tables(base: Dict, override: Dict) -> Dict:
        merged = {k: dict(v) for k, v in base.items()}
        for provider, models in override.items():
            merged.setdefault(provider, {})
            merged[provider] = {**merged[provider], **models}
        return merged

    def record(self, provider: Optional[str], model: Optional[str], usage: Optional[Dict]) -> Optional[float]:
        cost = compute_cost(self.pricing_table, provider, model, usage)
        if cost is not None:
            self.cumulative_cost_usd += cost
        return cost

    def is_over_budget(self) -> bool:
        if self.budget_usd_per_month is None:
            return False
        return self.cumulative_cost_usd >= self.budget_usd_per_month
