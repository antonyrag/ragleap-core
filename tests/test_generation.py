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
