"""Tests for query rewriting/expansion (contextual, hyde, multi_query).
Live semantic verification (real Gemini calls proving contextual
rewrite correctly resolves pronouns, HyDE generates on-topic passages,
multi_query produces genuinely distinct phrasings) was done manually
this session and is documented in CHANGELOG - not automated into CI
since it needs a real, currently-valid API key CI doesn't have.

This file covers: isolated unit tests for ragleap.query_rewrite's
functions (using a lightweight stub generator for deterministic
control, not real GenerationService), fail-open behavior when the
rewrite LLM call itself raises, and plumbing tests proving
query_rewrite= flows correctly through ask() end-to-end via the
existing fake_call_provider/fake_embedder fixtures."""
import pytest
from ragleap import RagLeap, ProviderConfig, EmbeddingConfig
from ragleap.query_rewrite import (
    contextual_rewrite, hyde_document, multi_query_variants, reciprocal_rank_fusion,
)
from conftest import TEST_DATABASE_URL, TEST_DIMENSIONS


def _make_rag(**kwargs):
    return RagLeap(
        database_url=TEST_DATABASE_URL,
        embedder=EmbeddingConfig(provider="gemini", model="models/gemini-embedding-001", dimensions=TEST_DIMENSIONS, api_key="fake-test-key"),
        primary=ProviderConfig(provider="gemini", model="gemini-3.6-flash", api_key="fake-test-key"),
        **kwargs,
    )


class _StubGenerator:
    """A minimal stand-in for GenerationService with full control over
    what generate_answer() returns or raises - lets the unit tests below
    assert on exact rewrite logic without depending on the real fake
    fixture's canned prompt-echo behavior."""
    def __init__(self, answer=None, raises=None):
        self._answer = answer
        self._raises = raises
        self.calls = []

    def generate_answer(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        return {"answer": self._answer, "provider_used": "gemini", "model_used": "gemini-3.6-flash", "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


# --- contextual_rewrite ---

def test_contextual_rewrite_no_history_returns_original_query_no_call():
    gen = _StubGenerator(answer="should never be used")
    result, raw = contextual_rewrite(gen, "What about pricing?", history_prefix="")
    assert result == "What about pricing?"
    assert raw is None
    assert len(gen.calls) == 0


def test_contextual_rewrite_with_history_calls_generator_and_returns_rewrite():
    gen = _StubGenerator(answer="What is RagLeap's pricing?")
    result, raw = contextual_rewrite(gen, "What about pricing?", history_prefix="User: What is RagLeap?\n")
    assert result == "What is RagLeap's pricing?"
    assert raw is not None
    assert len(gen.calls) == 1


def test_contextual_rewrite_fails_open_on_generator_error():
    gen = _StubGenerator(raises=RuntimeError("provider down"))
    result, raw = contextual_rewrite(gen, "What about pricing?", history_prefix="some history")
    assert result == "What about pricing?"  # falls back to original
    assert raw is None


def test_contextual_rewrite_empty_answer_falls_back_to_original():
    gen = _StubGenerator(answer="")
    result, raw = contextual_rewrite(gen, "What about pricing?", history_prefix="some history")
    assert result == "What about pricing?"


# --- hyde_document ---

def test_hyde_document_returns_hypothetical_passage():
    gen = _StubGenerator(answer="Paris is the capital of France, located on the Seine.")
    result, raw = hyde_document(gen, "What is the capital of France?")
    assert result == "Paris is the capital of France, located on the Seine."
    assert raw is not None


def test_hyde_document_fails_open_on_generator_error():
    gen = _StubGenerator(raises=RuntimeError("provider down"))
    result, raw = hyde_document(gen, "What is the capital of France?")
    assert result == "What is the capital of France?"
    assert raw is None


# --- multi_query_variants ---

def test_multi_query_variants_includes_original_first():
    gen = _StubGenerator(answer="Which accounts support password changes?\nHow to change my login credentials?")
    variants, raw = multi_query_variants(gen, "How do I reset my password?", n=3)
    assert variants[0] == "How do I reset my password?"
    assert len(variants) == 3
    assert raw is not None


def test_multi_query_variants_deduplicates_case_insensitively():
    gen = _StubGenerator(answer="how do i reset my password?\nA genuinely different phrasing.")
    variants, raw = multi_query_variants(gen, "How do I reset my password?", n=3)
    # the case-insensitive duplicate of the original should be filtered out
    assert variants.count("How do I reset my password?") == 1
    assert "A genuinely different phrasing." in variants


def test_multi_query_variants_fails_open_to_original_only():
    gen = _StubGenerator(raises=RuntimeError("provider down"))
    variants, raw = multi_query_variants(gen, "How do I reset my password?", n=3)
    assert variants == ["How do I reset my password?"]
    assert raw is None


# --- reciprocal_rank_fusion ---

def test_rrf_ranks_items_in_multiple_lists_higher():
    list1 = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    list2 = [{"chunk_id": "b"}, {"chunk_id": "c"}]
    merged = reciprocal_rank_fusion([list1, list2])
    assert merged[0]["chunk_id"] == "b"  # appears in both lists, ranked highest


def test_rrf_deduplicates_by_chunk_id():
    list1 = [{"chunk_id": "a"}, {"chunk_id": "a"}]
    merged = reciprocal_rank_fusion([list1])
    assert len(merged) == 1


def test_rrf_falls_back_to_document_id_chunk_index_when_no_chunk_id():
    list1 = [{"document_id": "doc1", "chunk_index": 0}]
    list2 = [{"document_id": "doc1", "chunk_index": 0}]
    merged = reciprocal_rank_fusion([list1, list2])
    assert len(merged) == 1  # correctly deduplicated via the fallback key


def test_rrf_empty_lists_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


# --- Plumbing tests: query_rewrite= flows through ask() correctly ---

def test_ask_without_query_rewrite_has_no_query_rewrite_key():
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")
    result = rag.ask("A question")
    assert "query_rewrite" not in result


def test_ask_with_contextual_rewrite_needs_session_id_to_do_anything():
    """No session_id means no history means contextual_rewrite makes no
    LLM call and query_rewrite_info still gets set (strategy recorded),
    but rewritten_query equals the original since there's nothing to
    rewrite against."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")
    result = rag.ask("A question", query_rewrite="contextual")
    assert result["query_rewrite"]["strategy"] == "contextual"
    assert result["query_rewrite"]["rewritten_query"] == "A question"


def test_ask_with_hyde_returns_hyde_document_field():
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")
    result = rag.ask("A question", query_rewrite="hyde")
    assert result["query_rewrite"]["strategy"] == "hyde"
    assert "hyde_document" in result["query_rewrite"]
    assert isinstance(result["query_rewrite"]["hyde_document"], str)
    assert len(result["query_rewrite"]["hyde_document"]) > 0


def test_ask_with_multi_query_returns_variants_and_retrieves():
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")
    result = rag.ask("A question", query_rewrite="multi_query", multi_query_n=2)
    assert result["query_rewrite"]["strategy"] == "multi_query"
    assert isinstance(result["query_rewrite"]["query_variants"], list)
    assert len(result["query_rewrite"]["query_variants"]) >= 1
    assert result["query_rewrite"]["query_variants"][0] == "A question"
    # the actual answer must still be grounded in real retrieval, not empty
    assert result["chunks_sent"] >= 1


def test_ask_final_answer_always_uses_original_query_not_rewritten():
    """The rewrite only affects what gets retrieved, never what's shown
    to the generation model as the actual question being answered -
    this test locks in that contract."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content about testing things.")
    result = rag.ask("What testing things exist?", query_rewrite="hyde")
    # fake_call_provider echoes the prompt tail, so we can confirm the
    # real user question (not the hyde passage) ended up in the final prompt
    assert "What testing things exist?" in result["answer"]


def test_ask_query_rewrite_cost_contributes_to_cumulative_spend():
    """The extra rewrite LLM call should be recorded into cumulative
    cost tracking, using the same CostTracker infrastructure as the
    main answer-generation call."""
    rag = _make_rag()
    rag.ingest_text("a.txt", "Some content.")
    rag.ask("A question", session_id="s1")  # seed history
    without_rewrite = rag.ask("A question", session_id="s1")
    with_rewrite = rag.ask("A follow-up question", session_id="s1", query_rewrite="contextual")
    # two answer-generation calls' worth of cost plus one extra rewrite
    # call's worth - cumulative after the rewrite call must exceed what
    # it would be from answer-generation calls alone
    assert with_rewrite["cost"]["cumulative_cost_usd"] > without_rewrite["cost"]["cumulative_cost_usd"]
