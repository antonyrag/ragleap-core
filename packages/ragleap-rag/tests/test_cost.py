"""Tests for cost tracking - per-call USD cost computation from real
provider-reported token usage, and budget-triggered fallback to a
cheaper/local provider on subsequent calls."""
import pytest
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.cost import compute_cost, CostTracker, SEED_PRICING_TABLE
from conftest import TEST_DATABASE_URL, TEST_DIMENSIONS


def _make_rag(primary=None, **kwargs):
    return RagLeap(
        database_url=TEST_DATABASE_URL,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", api_key="fake-test-key", dimensions=TEST_DIMENSIONS),
        primary=primary or ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        **kwargs,
    )


# --- Unit tests: compute_cost() / CostTracker in isolation, no DB needed ---

def test_compute_cost_known_provider_model():
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    cost = compute_cost(SEED_PRICING_TABLE, "gemini", "gemini-3.6-flash", usage)
    # (10/1e6)*1.50 + (5/1e6)*7.50 = 0.0000525, rounded to 6dp -> 0.000053
    assert cost == pytest.approx(0.000053, abs=1e-9)


def test_compute_cost_unknown_provider_returns_none():
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    assert compute_cost(SEED_PRICING_TABLE, "some-new-provider", "some-model", usage) is None


def test_compute_cost_unknown_model_returns_none():
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    # "gemini-2.5-flash" (no "-lite") is deliberately not in the seed table
    assert compute_cost(SEED_PRICING_TABLE, "gemini", "gemini-2.5-flash", usage) is None


def test_compute_cost_no_usage_returns_none():
    assert compute_cost(SEED_PRICING_TABLE, "gemini", "gemini-3.6-flash", None) is None


def test_compute_cost_ollama_wildcard_is_zero():
    usage = {"prompt_tokens": 1000, "completion_tokens": 1000}
    assert compute_cost(SEED_PRICING_TABLE, "ollama", "llama3-anything", usage) == 0.0


def test_cost_tracker_pricing_table_override_wins():
    tracker = CostTracker(pricing_table={"gemini": {"gemini-2.5-flash": {"input": 0.05, "output": 0.10}}})
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    cost = tracker.record("gemini", "gemini-2.5-flash", usage)
    assert cost == pytest.approx(0.15)


def test_cost_tracker_override_does_not_remove_other_seed_models():
    """Overriding one model for a provider shouldn't wipe out the other
    seed-table entries for that same provider."""
    tracker = CostTracker(pricing_table={"gemini": {"gemini-2.5-flash": {"input": 0.05, "output": 0.10}}})
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    cost = tracker.record("gemini", "gemini-3.6-flash", usage)  # untouched seed entry
    assert cost == pytest.approx(0.000053, abs=1e-9)


def test_cost_tracker_accumulates_across_calls():
    tracker = CostTracker()
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    tracker.record("gemini", "gemini-3.6-flash", usage)
    tracker.record("gemini", "gemini-3.6-flash", usage)
    assert tracker.cumulative_cost_usd == pytest.approx(0.000053 * 2, abs=1e-9)


def test_cost_tracker_no_budget_set_is_never_over_budget():
    tracker = CostTracker()
    tracker.record("gemini", "gemini-3.6-flash", {"prompt_tokens": 999_999_999, "completion_tokens": 999_999_999})
    assert tracker.is_over_budget() is False


def test_cost_tracker_over_budget_after_threshold_crossed():
    tracker = CostTracker(budget_usd_per_month=0.00001)
    assert tracker.is_over_budget() is False  # nothing spent yet
    tracker.record("gemini", "gemini-3.6-flash", {"prompt_tokens": 10, "completion_tokens": 5})  # costs 0.0000525
    assert tracker.is_over_budget() is True


# --- Integration tests: real ask() wiring through RagLeap ---

def test_ask_result_has_cost_field_with_known_pricing():
    rag = _make_rag(primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"))
    rag.ingest_text("a.txt", "Some content about testing things.")

    result = rag.ask("A question")

    assert result["cost"]["pricing_available"] is True
    assert result["cost"]["cost_usd"] == pytest.approx(0.000053, abs=1e-9)
    assert result["cost"]["cumulative_cost_usd"] == pytest.approx(0.000053, abs=1e-9)


def test_ask_result_cost_unavailable_for_unpriced_model():
    """A model not in the seed pricing table - cost must honestly report
    unavailable, never guess. Uses an explicit, deliberately-fake model
    name rather than relying on "whatever the current default happens
    to be", since that default is not a stable thing to couple a test
    to (see: gemini-2.5-flash getting deprecated by Google mid-project)."""
    rag = _make_rag(primary=ProviderConfig(provider="gemini", model="some-future-unpriced-gemini-model", api_key="fake-test-key"))
    rag.ingest_text("a.txt", "Some content.")

    result = rag.ask("A question")

    assert result["cost"]["pricing_available"] is False
    assert result["cost"]["cost_usd"] is None


def test_ask_pricing_table_override_applies_through_rag_constructor():
    rag = _make_rag(
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        pricing_table={"gemini": {"gemini-3.6-flash": {"input": 0.05, "output": 0.10}}},
    )
    rag.ingest_text("a.txt", "Some content.")

    result = rag.ask("A question")

    assert result["cost"]["pricing_available"] is True
    # (10/1e6)*0.05 + (5/1e6)*0.10
    assert result["cost"]["cost_usd"] == pytest.approx(0.0000010, abs=1e-9)


def test_cumulative_cost_grows_across_multiple_ask_calls():
    rag = _make_rag(primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"))
    rag.ingest_text("a.txt", "Some content.")

    first = rag.ask("Q1")
    second = rag.ask("Q2")

    assert second["cost"]["cumulative_cost_usd"] == pytest.approx(first["cost"]["cost_usd"] * 2, abs=1e-9)


def test_budget_fallback_triggers_switch_to_fallback_provider():
    """First call stays on primary (nothing spent yet, so not over budget).
    Its real cost then crosses the tiny budget, so the second call must
    use budget_fallback instead - proving override_provider actually
    reaches the generation chain, not just that cost is tracked."""
    primary = ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key")
    fallback = ProviderConfig(provider="anthropic", api_key="fake-test-key", model="claude-haiku-4-5-20251001")
    rag = _make_rag(
        primary=primary,
        budget_usd_per_month=0.00001,  # lower than one call's real cost (~0.0000525)
        budget_fallback=fallback,
    )
    rag.ingest_text("a.txt", "Some content.")

    first = rag.ask("Q1")
    assert first["provider_used"] == "gemini"

    second = rag.ask("Q2")
    assert second["provider_used"] == "anthropic"


def test_no_budget_fallback_configured_never_switches_provider():
    """budget_usd_per_month set but no budget_fallback provider -> stays
    on primary regardless of spend, since there's nowhere to fall back to."""
    primary = ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key")
    rag = _make_rag(primary=primary, budget_usd_per_month=0.00001)
    rag.ingest_text("a.txt", "Some content.")

    rag.ask("Q1")
    second = rag.ask("Q2")

    assert second["provider_used"] == "gemini"


def test_ask_stream_cost_is_always_unavailable():
    """Streaming has no token usage data (see generate_answer_stream's
    docstring) - cost must honestly report unavailable, not fabricated."""
    rag = _make_rag(primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"))
    rag.ingest_text("a.txt", "Some content.")

    list(rag.ask_stream("A question"))
    # ask_stream doesn't return a result dict (it's a generator of text),
    # so we verify indirectly: cumulative cost stays at 0 since streaming
    # never records a real cost.
    assert rag._cost_tracker.cumulative_cost_usd == 0.0
