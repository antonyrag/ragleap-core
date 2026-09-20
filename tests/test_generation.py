"""
Tests for core/generation.py - provider-agnostic truncation retry safeguard.
No DB or live API required - _call_provider is mocked directly so this
tests generate_answer()'s retry logic in isolation from any real provider,
covering Gemini/Anthropic/OpenAI-compatible (including Ollama) alike since
they all normalize to a "finish_reason" key in the usage dict.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.generation import GenerationService
from core import generation


def _make_service(primary_provider="testprovider"):
    """Build a GenerationService without hitting _resolve_provider_config
    (which requires real env-configured API keys) - set primary_config
    directly instead."""
    service = object.__new__(GenerationService)
    service.primary_config = {"provider": primary_provider, "api_key": "x", "model": "m", "base_url": None}
    service.provider = primary_provider
    return service


def test_no_retry_when_not_truncated():
    service = _make_service()
    with patch.object(
        service, "_call_provider",
        return_value=("complete answer", {"finish_reason": "stop", "completion_tokens": 5}),
    ) as mock_call:
        result = service.generate_answer("question", [], max_tokens=100)
    assert mock_call.call_count == 1
    assert result["answer"] == "complete answer"
    assert result["usage"]["finish_reason"] == "stop"


def test_retries_once_on_truncation_and_uses_retry_result():
    service = _make_service()
    calls = []

    def fake_call(config, prompt, temperature, max_tokens):
        calls.append(max_tokens)
        if max_tokens == 100:
            return "truncated ans", {"finish_reason": "MAX_TOKENS", "completion_tokens": 100}
        return "complete answer after retry", {"finish_reason": "stop", "completion_tokens": 150}

    with patch.object(service, "_call_provider", side_effect=fake_call):
        result = service.generate_answer("question", [], max_tokens=100)

    assert calls == [100, 200]  # default 2x multiplier
    assert result["answer"] == "complete answer after retry"
    assert result["usage"]["finish_reason"] == "stop"


def test_retry_result_still_truncated_returns_it_anyway():
    """If the retry is ALSO truncated, generate_answer should still return
    that (larger) answer rather than looping forever - only one retry."""
    service = _make_service()
    calls = []

    def fake_call(config, prompt, temperature, max_tokens):
        calls.append(max_tokens)
        return f"truncated at {max_tokens}", {"finish_reason": "length", "completion_tokens": max_tokens}

    with patch.object(service, "_call_provider", side_effect=fake_call):
        result = service.generate_answer("question", [], max_tokens=100)

    assert calls == [100, 200]  # only ONE retry attempt, no loop
    assert result["answer"] == "truncated at 200"


def test_no_retry_when_already_at_max_retry_cap():
    """max_tok already >= TRUNCATION_MAX_RETRY_TOKENS should not retry."""
    service = _make_service()
    with patch.object(
        service, "_call_provider",
        return_value=("cut off", {"finish_reason": "MAX_TOKENS", "completion_tokens": generation.TRUNCATION_MAX_RETRY_TOKENS}),
    ) as mock_call:
        result = service.generate_answer("question", [], max_tokens=generation.TRUNCATION_MAX_RETRY_TOKENS)
    assert mock_call.call_count == 1
    assert result["answer"] == "cut off"


def test_retry_failure_falls_back_to_original_answer():
    """If the retry call itself raises, keep the original (possibly
    truncated) answer instead of crashing the whole request."""
    service = _make_service()
    calls = []

    def fake_call(config, prompt, temperature, max_tokens):
        calls.append(max_tokens)
        if max_tokens == 100:
            return "truncated ans", {"finish_reason": "MAX_TOKENS", "completion_tokens": 100}
        raise RuntimeError("provider unreachable on retry")

    with patch.object(service, "_call_provider", side_effect=fake_call):
        result = service.generate_answer("question", [], max_tokens=100)

    assert calls == [100, 200]
    assert result["answer"] == "truncated ans"


def test_ollama_style_finish_reason_triggers_retry():
    """OpenAI-compatible hosts (including Ollama) report finish_reason='length'."""
    service = _make_service(primary_provider="ollama")
    calls = []

    def fake_call(config, prompt, temperature, max_tokens):
        calls.append(max_tokens)
        if max_tokens == 50:
            return "cut", {"finish_reason": "length", "completion_tokens": 50}
        return "full answer", {"finish_reason": "stop", "completion_tokens": 80}

    with patch.object(service, "_call_provider", side_effect=fake_call):
        result = service.generate_answer("question", [], max_tokens=50)

    assert calls == [50, 100]
    assert result["answer"] == "full answer"


# --- Streaming truncation notice (generate_answer_stream) ---
# No true mid-stream retry is possible (tokens already sent to the caller),
# so instead of retrying, a truncated stream gets one honest closing note
# appended. _stream_provider is mocked directly, matching how _call_provider
# is mocked above for the blocking-path tests.

def test_stream_no_notice_when_complete():
    service = _make_service()

    def fake_stream(config, prompt, temperature, max_tokens, result_holder=None):
        yield "hello "
        yield "world"
        if result_holder is not None:
            result_holder["finish_reason"] = "stop"

    with patch.object(service, "_stream_provider", side_effect=fake_stream):
        pieces = list(service.generate_answer_stream("question", []))

    full = "".join(pieces)
    assert full == "hello world"
    assert "cut short" not in full


def test_stream_appends_notice_when_truncated_gemini_style():
    service = _make_service()

    def fake_stream(config, prompt, temperature, max_tokens, result_holder=None):
        yield "partial answ"
        if result_holder is not None:
            result_holder["finish_reason"] = "MAX_TOKENS"

    with patch.object(service, "_stream_provider", side_effect=fake_stream):
        pieces = list(service.generate_answer_stream("question", []))

    full = "".join(pieces)
    assert full.startswith("partial answ")
    assert "cut short" in full


def test_stream_appends_notice_when_truncated_openai_style():
    service = _make_service()

    def fake_stream(config, prompt, temperature, max_tokens, result_holder=None):
        yield "cut off resu"
        if result_holder is not None:
            result_holder["finish_reason"] = "length"

    with patch.object(service, "_stream_provider", side_effect=fake_stream):
        pieces = list(service.generate_answer_stream("question", []))

    full = "".join(pieces)
    assert "cut short" in full


def test_stream_appends_notice_when_truncated_anthropic_style():
    service = _make_service()

    def fake_stream(config, prompt, temperature, max_tokens, result_holder=None):
        yield "half a thou"
        if result_holder is not None:
            result_holder["finish_reason"] = "max_tokens"

    with patch.object(service, "_stream_provider", side_effect=fake_stream):
        pieces = list(service.generate_answer_stream("question", []))

    full = "".join(pieces)
    assert "cut short" in full


def test_stream_no_notice_when_provider_fails_before_yielding():
    """If a provider errors before yielding anything and before ever
    setting finish_reason, the existing error-handling path takes over -
    no truncation notice should be appended on top of that."""
    service = _make_service()

    def fake_stream(config, prompt, temperature, max_tokens, result_holder=None):
        raise RuntimeError("boom")
        yield  # pragma: no cover - keeps this a generator function

    with patch.object(service, "_stream_provider", side_effect=fake_stream):
        pieces = list(service.generate_answer_stream("question", []))

    full = "".join(pieces)
    assert "cut short" not in full
    assert "all configured providers failed" in full


# --- Self-correction/reflection: check_grounding() ---
# Item #3 of the 9-pattern agentic-architecture build. _call_provider is
# mocked directly, same pattern as every other test in this file.

def test_check_grounding_returns_none_when_grounded():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("GROUNDED", None)):
        concern = service.check_grounding("The refund window is 30 days.", [{"text": "Refunds within 30 days."}], "what is the refund policy?")
    assert concern is None


def test_check_grounding_returns_reason_when_not_grounded():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("NOT_GROUNDED: the 30-day figure is not in the source", None)):
        concern = service.check_grounding("The refund window is 30 days.", [{"text": "We offer refunds."}], "what is the refund policy?")
    assert concern == "the 30-day figure is not in the source"


def test_check_grounding_generic_reason_when_no_colon():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("NOT_GROUNDED", None)):
        concern = service.check_grounding("answer", [], "question")
    assert concern == "unsupported claim detected"


def test_check_grounding_returns_none_on_provider_failure():
    """Best-effort: a failure in the check itself must never propagate
    or block the caller - treated as inconclusive."""
    service = _make_service()
    with patch.object(service, "_call_provider", side_effect=RuntimeError("provider down")):
        concern = service.check_grounding("answer", [], "question")
    assert concern is None


def test_check_grounding_uses_primary_config_not_fallback_chain():
    service = _make_service(primary_provider="gemini")
    with patch.object(service, "_call_provider", return_value=("GROUNDED", None)) as mock_call:
        service.check_grounding("answer", [], "question")
    called_config = mock_call.call_args[0][0]
    assert called_config is service.primary_config
    assert mock_call.call_args.kwargs.get("temperature") == 0.0


# --- Chain of thought (item #4): reasoning_mode ---
from core import generation as _gen
from core.generation import _split_reasoning_and_answer


def test_split_reasoning_marker_present():
    r, a = _split_reasoning_and_answer("REASONING: step one, step two.\n\nFINAL ANSWER: The refund window is 30 days.")
    assert a == "The refund window is 30 days."
    assert r == "step one, step two."


def test_split_reasoning_marker_case_insensitive():
    r, a = _split_reasoning_and_answer("reasoning: thinking here\nfinal answer: Yes, covered.")
    assert a == "Yes, covered."
    assert r == "thinking here"


def test_split_reasoning_marker_absent_falls_back_to_full_text():
    r, a = _split_reasoning_and_answer("Just a plain answer with no markers.")
    assert r is None
    assert a == "Just a plain answer with no markers."


def test_split_reasoning_empty_answer_after_marker_falls_back():
    text = "REASONING: something\nFINAL ANSWER:   "
    r, a = _split_reasoning_and_answer(text)
    assert r is None
    assert a == text


def test_generate_answer_reasoning_mode_true():
    service = _make_service()
    raw = "REASONING: chunk says 30 days.\nFINAL ANSWER: Refunds are allowed within 30 days."
    with patch.object(service, "_call_provider", return_value=(raw, {"finish_reason": "stop"})) as mock_call:
        result = service.generate_answer("refund?", [{"document_name": "d", "content": "30 days"}], reasoning_mode=True)
    args = mock_call.call_args.args
    assert "FINAL ANSWER:" in args[1]
    assert args[3] == int(_gen.MAX_OUTPUT_TOKENS * _gen.REASONING_MODE_TOKEN_MULTIPLIER)
    assert result["answer"] == "Refunds are allowed within 30 days."
    assert result["reasoning"] == "chunk says 30 days."


def test_generate_answer_reasoning_mode_false_unchanged():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("plain", {"finish_reason": "stop"})) as mock_call:
        result = service.generate_answer("q?", [{"document_name": "d", "content": "c"}])
    args = mock_call.call_args.args
    assert "FINAL ANSWER:" not in args[1]
    assert args[3] == _gen.MAX_OUTPUT_TOKENS
    assert result["answer"] == "plain"
    assert result["reasoning"] is None


def test_generate_answer_reasoning_mode_no_marker_never_breaks():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("model ignored the format", {"finish_reason": "stop"})):
        result = service.generate_answer("q?", [{"document_name": "d", "content": "c"}], reasoning_mode=True)
    assert result["answer"] == "model ignored the format"
    assert result["reasoning"] is None


def test_generate_answer_all_providers_failed_has_reasoning_and_fallback_keys():
    service = _make_service()
    with patch.object(service, "_call_provider", side_effect=Exception("boom")):
        result = service.generate_answer("q?", [{"document_name": "d", "content": "c"}], reasoning_mode=True)
    assert result["provider_used"] is None
    assert result["reasoning"] is None
    assert result["fallback_used"] is False


# --- Tree of thought (item #5): opt-in tot_mode ---
_TOT_CHUNKS = [{"document_name": "d", "content": "c"}]


def test_tot_picks_candidate_chosen_by_judge():
    service = _make_service()
    replies = [("cand one", None), ("cand two", None), ("cand three", None), ("2", None)]
    with patch.object(service, "_call_provider", side_effect=replies) as mock_call:
        result = service.tree_of_thought("q?", _TOT_CHUNKS, 0.3)
    assert mock_call.call_count == 4
    assert result["answer"] == "cand two"
    assert "chosen=2" in result["reasoning"]


def test_tot_garbage_judge_reply_uses_first_candidate():
    service = _make_service()
    replies = [("cand one", None), ("cand two", None), ("cand three", None), ("no idea", None)]
    with patch.object(service, "_call_provider", side_effect=replies):
        result = service.tree_of_thought("q?", _TOT_CHUNKS, 0.3)
    assert result["answer"] == "cand one"
    assert "by=default" in result["reasoning"]


def test_tot_judge_failure_uses_first_candidate():
    service = _make_service()
    replies = [("cand one", None), ("cand two", None), ("cand three", None), Exception("judge down")]
    with patch.object(service, "_call_provider", side_effect=replies):
        result = service.tree_of_thought("q?", _TOT_CHUNKS, 0.3)
    assert result["answer"] == "cand one"


def test_tot_returns_none_when_fewer_than_two_candidates():
    service = _make_service()
    replies = [("only one", None), Exception("boom"), Exception("boom")]
    with patch.object(service, "_call_provider", side_effect=replies):
        assert service.tree_of_thought("q?", _TOT_CHUNKS, 0.3) is None


def test_generate_answer_tot_mode_true_returns_tot_answer_and_reasoning():
    service = _make_service()
    replies = [("a1", None), ("a2", None), ("a3", None), ("3", None)]
    with patch.object(service, "_call_provider", side_effect=replies):
        result = service.generate_answer("q?", _TOT_CHUNKS, tot_mode=True)
    assert result["answer"] == "a3"
    assert result["provider_used"] == "testprovider"
    assert result["reasoning"].startswith("TREE OF THOUGHT")


def test_generate_answer_tot_mode_falls_back_to_normal_answer():
    service = _make_service()
    replies = [("x", None), Exception("boom"), Exception("boom"),
               ("normal answer", {"finish_reason": "stop"})]
    with patch.object(service, "_call_provider", side_effect=replies):
        result = service.generate_answer("q?", _TOT_CHUNKS, tot_mode=True)
    assert result["answer"] == "normal answer"
    assert result["reasoning"] is None


def test_generate_answer_tot_mode_false_never_calls_tree_of_thought():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("plain", {"finish_reason": "stop"})), \
         patch.object(service, "tree_of_thought") as mock_tot:
        service.generate_answer("q?", _TOT_CHUNKS)
    mock_tot.assert_not_called()


def test_tot_judge_call_gets_enough_token_budget():
    service = _make_service()
    replies = [("c1", None), ("c2", None), ("c3", None), ("2", None)]
    with patch.object(service, "_call_provider", side_effect=replies) as mock_call:
        service.tree_of_thought("q?", _TOT_CHUNKS, 0.3)
    assert mock_call.call_args_list[-1].args[3] == _gen.TOT_JUDGE_MAX_TOKENS
    assert _gen.TOT_JUDGE_MAX_TOKENS >= 100


def test_tot_judge_empty_reply_is_retried_with_bigger_budget():
    service = _make_service()
    replies = [("c1", None), ("c2", None), ("c3", None), ("", None), ("3", None)]
    with patch.object(service, "_call_provider", side_effect=replies) as mock_call:
        result = service.tree_of_thought("q?", _TOT_CHUNKS, 0.3)
    assert mock_call.call_count == 5
    assert mock_call.call_args_list[-1].args[3] == _gen.TOT_JUDGE_MAX_TOKENS * 2
    assert result["answer"] == "c3"
    assert "by=judge" in result["reasoning"]


# --- check_grounding token budget (empty-reply hardening) ---
def test_check_grounding_uses_bigger_budget_and_flags_concern():
    service = _make_service()
    with patch.object(service, "_call_provider", return_value=("NOT_GROUNDED: invented claim", None)) as mock_call:
        result = service.check_grounding("ans", _TOT_CHUNKS, "q?")
    assert result == "invented claim"
    assert mock_call.call_args.kwargs["max_tokens"] == _gen.GROUNDING_CHECK_MAX_TOKENS
    assert _gen.GROUNDING_CHECK_MAX_TOKENS >= 300


def test_check_grounding_empty_reply_is_retried_with_bigger_budget():
    service = _make_service()
    replies = [("", None), ("NOT_GROUNDED: unsupported", None)]
    with patch.object(service, "_call_provider", side_effect=replies) as mock_call:
        result = service.check_grounding("ans", _TOT_CHUNKS, "q?")
    assert mock_call.call_count == 2
    assert mock_call.call_args_list[-1].kwargs["max_tokens"] == _gen.GROUNDING_CHECK_MAX_TOKENS * 2
    assert result == "unsupported"
