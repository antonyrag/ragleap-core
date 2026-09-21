"""Tests for core/budget.py, the usage-recording wrapper and the budget check in ask(). No network; DB mocked."""
import logging
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import budget, chat
from core.generation import GenerationService

CAPS = ("BUDGET_DAILY_TOKENS", "BUDGET_MONTHLY_TOKENS", "BUDGET_ROLE_DAILY_TOKENS",
        "BUDGET_ROLE_MONTHLY_TOKENS", "BUDGET_ROLE_DAILY_OVERRIDES", "BUDGET_ROLE_MONTHLY_OVERRIDES", "USAGE_LEDGER")


def _env(**kw):
    clean = {k: v for k, v in os.environ.items() if k not in CAPS}
    clean.update(kw)
    return patch.dict(os.environ, clean, clear=True)


def _conn(*used):
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.side_effect = [(u,) for u in used]
    return conn


def test_estimate_tokens():
    assert budget.estimate_tokens("") == 0 and budget.estimate_tokens(None) == 0
    assert budget.estimate_tokens("a") == 1 and budget.estimate_tokens("a" * 4) == 1
    assert budget.estimate_tokens("a" * 5) == 2 and budget.estimate_tokens("a" * 40) == 10


def test_record_usage_uses_reported_tokens():
    conn = _conn()
    budget.set_role("support")
    with _env(), patch.object(budget, "get_connection", return_value=conn):
        budget.record_usage("gemini", "m", "prompt", "reply", {"prompt_tokens": 5, "completion_tokens": 7})
    params = conn.cursor.return_value.execute.call_args.args[1]
    assert params == ("support", "gemini", "m", 5, 7, 12, False)
    conn.commit.assert_called_once()


def test_record_usage_estimates_when_provider_reports_nothing():
    conn = _conn()
    budget.set_role(None)
    with _env(), patch.object(budget, "get_connection", return_value=conn):
        budget.record_usage("ollama", "llama3", "p" * 40, "r" * 8, None)
    assert conn.cursor.return_value.execute.call_args.args[1] == (None, "ollama", "llama3", 10, 2, 12, True)


def test_record_usage_partial_usage_estimates_the_missing_part():
    conn = _conn()
    with _env(), patch.object(budget, "get_connection", return_value=conn):
        budget.record_usage("x", "m", "p" * 40, "r" * 8, {"prompt_tokens": 100})
    params = conn.cursor.return_value.execute.call_args.args[1]
    assert params[3:] == (100, 2, 102, True)


def test_record_usage_can_be_disabled_and_never_raises():
    with _env(USAGE_LEDGER="off"), patch.object(budget, "get_connection") as g:
        budget.record_usage("x", "m", "p", "r", None)
    g.assert_not_called()
    with _env(), patch.object(budget, "get_connection", side_effect=Exception("db down")):
        budget.record_usage("x", "m", "p", "r", None)


def test_no_caps_means_no_database_access():
    with _env(), patch.object(budget, "get_connection") as g:
        assert budget.check_budget("support") is None and budget.check_budget(None) is None
    g.assert_not_called()


def test_global_daily_cap_blocks_and_under_cap_passes():
    with _env(BUDGET_DAILY_TOKENS="100"), patch.object(budget, "get_connection", return_value=_conn(150)):
        b = budget.check_budget(None)
    assert b["scope"] == "global" and b["period"] == "day" and b["limit"] == 100 and b["used"] == 150
    with _env(BUDGET_DAILY_TOKENS="100"), patch.object(budget, "get_connection", return_value=_conn(10)):
        assert budget.check_budget(None) is None


def test_global_monthly_cap_blocks_when_daily_is_fine():
    conns = [_conn(10), _conn(900)]
    with _env(BUDGET_DAILY_TOKENS="100", BUDGET_MONTHLY_TOKENS="500"), \
         patch.object(budget, "get_connection", side_effect=lambda: conns.pop(0)):
        b = budget.check_budget(None)
    assert b["period"] == "month" and b["scope"] == "global"


def test_role_cap_only_applies_to_that_role_and_filters_by_role():
    conn = _conn(60)
    with _env(BUDGET_ROLE_DAILY_TOKENS="50"), patch.object(budget, "get_connection", return_value=conn):
        b = budget.check_budget("support")
    assert b["scope"] == "role" and b["role"] == "support"
    sql, params = conn.cursor.return_value.execute.call_args.args
    assert "role = %s" in sql and params == ("support",)
    with _env(BUDGET_ROLE_DAILY_TOKENS="50"), patch.object(budget, "get_connection") as g:
        assert budget.check_budget(None) is None
    g.assert_not_called()


def test_role_overrides_and_zero_means_unlimited():
    with _env(BUDGET_ROLE_DAILY_TOKENS="1000", BUDGET_ROLE_DAILY_OVERRIDES="support=10"), \
         patch.object(budget, "get_connection", return_value=_conn(20)):
        assert budget.check_budget("support")["limit"] == 10
    with _env(BUDGET_ROLE_DAILY_TOKENS="1000", BUDGET_ROLE_DAILY_OVERRIDES="sales=0"), \
         patch.object(budget, "get_connection") as g:
        assert budget.check_budget("sales") is None
    g.assert_not_called()


def test_bad_env_values_are_ignored():
    with _env(BUDGET_DAILY_TOKENS="abc", BUDGET_ROLE_DAILY_OVERRIDES="x=,y=notnum,=5,z"), \
         patch.object(budget, "get_connection") as g:
        assert budget.check_budget("x") is None
    g.assert_not_called()


def test_check_fails_open_on_database_error():
    with _env(BUDGET_DAILY_TOKENS="100"), patch.object(budget, "get_connection", side_effect=Exception("db down")):
        assert budget.check_budget(None) is None


def test_warning_logged_at_eighty_percent(caplog):
    with _env(BUDGET_DAILY_TOKENS="100"), patch.object(budget, "get_connection", return_value=_conn(85)), \
         caplog.at_level(logging.WARNING, logger="core.budget"):
        assert budget.check_budget(None) is None
    assert "Budget warning" in caplog.text


def test_call_provider_wrapper_records_and_returns_unchanged():
    s = object.__new__(GenerationService)
    usage = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
    with patch.object(s, "_call_provider_raw", return_value=("reply", usage)), \
         patch("core.budget.record_usage") as rec:
        out = s._call_provider({"provider": "gemini", "model": "m"}, "prompt", 0.0, 10)
    assert out == ("reply", usage)
    rec.assert_called_once_with("gemini", "m", "prompt", "reply", usage)


def test_call_provider_wrapper_survives_recording_failure():
    s = object.__new__(GenerationService)
    with patch.object(s, "_call_provider_raw", return_value=("reply", None)), \
         patch("core.budget.record_usage", side_effect=Exception("boom")):
        assert s._call_provider({"provider": "x", "model": "m"}, "p", 0.0, 10) == ("reply", None)


def _gen():
    gen = MagicMock()
    gen.return_value.generate_answer.return_value = {
        "answer": "a", "sources": [], "provider_used": "gemini", "usage": {}, "chunks_sent": 1,
        "fallback_used": False, "reasoning": None,
    }
    return gen


def test_ask_blocked_by_budget_skips_the_whole_pipeline_and_traces_it():
    gen = _gen()
    blocked = {"scope": "global", "role": None, "period": "day", "limit": 100, "used": 150}
    with patch.object(chat.budget, "check_budget", return_value=blocked), \
         patch.object(chat, "GenerationService", gen), patch.object(chat, "_prepare") as prep, \
         patch.object(chat, "record_trace") as trace:
        r = chat.ask("q?")
    assert r["answer"] == budget.BUDGET_MESSAGE and r["provider_used"] is None
    assert r["budget_exceeded"] == {"scope": "global", "period": "day"} and "used" not in str(r["budget_exceeded"])
    gen.return_value.generate_answer.assert_not_called()
    prep.assert_not_called()
    assert "budget reached" in trace.call_args.kwargs["error"]


def test_ask_not_blocked_runs_normally():
    gen = _gen()
    with patch.object(chat.budget, "check_budget", return_value=None), \
         patch.object(chat, "GenerationService", gen), \
         patch.object(chat, "_prepare", return_value=([{"document_name": "d"}], "en", False)), \
         patch.object(chat, "record_trace"):
        r = chat.ask("q?")
    assert r["answer"] == "a" and "budget_exceeded" not in r


def test_ask_auto_checks_global_first_then_the_routed_role():
    gen = _gen()
    seen = []
    def fake_check(role=None):
        seen.append(role)
        return None
    route = MagicMock(return_value={"role": "sales", "reason": "r", "method": "llm"})
    with patch.object(chat.budget, "check_budget", side_effect=fake_check), \
         patch.object(chat, "GenerationService", gen), patch.object(chat, "route_task", route), \
         patch.object(chat, "_prepare", return_value=([{"document_name": "d"}], "en", False)), \
         patch.object(chat, "_build_system_prompt", return_value=(None, [])), \
         patch.object(chat, "_augment_query_with_reminder", return_value="q?"), \
         patch.object(chat, "record_trace"):
        chat.ask("q?", role="auto")
    assert seen == [None, "sales"] and budget.get_role() == "sales"


def test_ask_auto_blocked_after_routing_when_role_cap_reached():
    gen = _gen()
    route = MagicMock(return_value={"role": "sales", "reason": "r", "method": "llm"})
    blocked = {"scope": "role", "role": "sales", "period": "day", "limit": 10, "used": 20}
    with patch.object(chat.budget, "check_budget", side_effect=[None, blocked]), \
         patch.object(chat, "GenerationService", gen), patch.object(chat, "route_task", route), \
         patch.object(chat, "_prepare") as prep, patch.object(chat, "record_trace"):
        r = chat.ask("q?", role="auto")
    assert r["budget_exceeded"] == {"scope": "role", "period": "day"}
    prep.assert_not_called()
