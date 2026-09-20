"""Tests for core/employees/actions.py (phase 2): no network, the LLM and the gate are mocked."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.employees import actions as act

FULL = {
    "WEBHOOK_TARGETS": "n8n=https://hooks.example.com/secret-abc",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/x",
    "SMTP_HOST": "smtp.example.com",
    "EMAIL_ALLOWED_RECIPIENTS": "boss@acme.com,@partner.com",
}


def _env(**kw):
    return patch.dict(os.environ, kw, clear=True)


def _svc(*replies):
    s = MagicMock()
    s.primary_config = {"provider": "x"}
    s._call_provider.side_effect = [r if isinstance(r, Exception) else (r, None) for r in replies]
    return s


def test_available_tools_none_when_nothing_configured():
    with _env():
        assert act.available_tools() == {}


def test_available_tools_lists_configured_without_secrets():
    with _env(**FULL):
        tools = act.available_tools()
    assert set(tools) == {"send_webhook", "send_slack", "send_email"}
    assert "n8n" in tools["send_webhook"] and "boss@acme.com" in tools["send_email"]
    assert "secret-abc" not in "".join(tools.values())


def test_available_tools_partial_configuration():
    with _env(SLACK_WEBHOOK_URL=FULL["SLACK_WEBHOOK_URL"]):
        assert set(act.available_tools()) == {"send_slack"}
    with _env(SMTP_HOST="smtp.example.com"):
        assert act.available_tools() == {}


def test_parse_plan_variants():
    assert act._parse_plan('{"tool":"none"}') == {"tool": "none"}
    assert act._parse_plan('```json\n{"tool":"send_slack","content":"hi"}\n```')["tool"] == "send_slack"
    for bad in ("nothing", "[1,2]", "{bad json}", ""):
        assert act._parse_plan(bad) is None


def test_validate_rejects_bad_plans():
    with _env(**FULL):
        tools = act.available_tools()
        for plan in (
            {"tool": "none"},
            {"tool": "delete_everything", "content": "x"},
            {"tool": "send_slack", "content": ""},
            {"tool": "send_webhook", "target": "evil", "content": "x"},
            {"tool": "send_webhook", "target": "https://evil.com", "content": "x"},
            {"tool": "send_email", "target": "stranger@evil.com", "content": "x"},
        ):
            assert act._validate_plan(plan, tools) is None, plan
    with _env(SLACK_WEBHOOK_URL=FULL["SLACK_WEBHOOK_URL"]):
        assert act._validate_plan({"tool": "send_email", "target": "boss@acme.com", "content": "x"},
                                  act.available_tools()) is None


def test_validate_accepts_good_plans_and_ignores_model_slack_target():
    with _env(**FULL):
        tools = act.available_tools()
        v = act._validate_plan({"tool": "send_webhook", "target": "n8n", "content": "hello"}, tools)
        assert v["channel"] == "webhook" and v["target"] == "n8n"
        v = act._validate_plan({"tool": "send_slack", "target": "http://evil.com", "content": "hi"}, tools)
        assert v["target"] == "slack"
        v = act._validate_plan({"tool": "send_email", "target": "boss@acme.com", "subject": "Hi", "content": "body"}, tools)
        assert v["content"].startswith("Subject: Hi\n\n")
        assert act._validate_plan({"tool": "send_email", "target": "anyone@partner.com", "content": "x"}, tools)
        v = act._validate_plan({"tool": "send_slack", "content": "y" * 99999}, tools)
        assert len(v["content"]) == act.MAX_ACTION_CONTENT


def test_validate_email_subject_cannot_inject_headers():
    with _env(**FULL):
        v = act._validate_plan({"tool": "send_email", "target": "boss@acme.com",
                                "subject": "A\nBcc: x@evil.com", "content": "b"}, act.available_tools())
    assert v["content"].split("\n")[0] == "Subject: A Bcc: x@evil.com"


def test_plan_action_happy_path():
    svc = _svc('{"tool":"send_slack","content":"hi team"}')
    with _env(**FULL):
        plan = act.plan_action("post hi to slack", "ans", svc)
    assert plan["tool"] == "send_slack" and svc._call_provider.call_count == 1


def test_plan_action_no_tools_makes_no_llm_call():
    svc = _svc('{"tool":"send_slack","content":"x"}')
    with _env():
        assert act.plan_action("post hi", "ans", svc) is None
    svc._call_provider.assert_not_called()


def test_plan_action_none_tool_returns_none():
    with _env(**FULL):
        assert act.plan_action("just a question", "ans", _svc('{"tool": "none"}')) is None


def test_plan_action_empty_reply_retried_with_bigger_budget():
    svc = _svc("", '{"tool":"send_slack","content":"x"}')
    with _env(**FULL):
        plan = act.plan_action("post x", "ans", svc)
    assert plan and svc._call_provider.call_count == 2
    assert svc._call_provider.call_args_list[-1].args[3] == act.ACTION_PLAN_MAX_TOKENS * 2


def test_plan_action_provider_failure_returns_none():
    with _env(**FULL):
        assert act.plan_action("post x", "ans", _svc(Exception("boom"))) is None


def test_prompt_hides_urls_and_marks_untrusted_text():
    svc = _svc('{"tool":"none"}')
    with _env(**FULL):
        act.plan_action("REQ TEXT", "ANS TEXT", svc)
    prompt = svc._call_provider.call_args.args[1]
    assert "<request>\nREQ TEXT\n</request>" in prompt and "<answer>\nANS TEXT\n</answer>" in prompt
    assert "secret-abc" not in prompt and "hooks.slack.com" not in prompt
    assert "context only" in prompt.lower()


def test_run_action_passes_role_and_action_type_to_the_gate():
    plan = {"tool": "send_email", "channel": "email", "target": "boss@acme.com", "content": "c", "subject": "s"}
    with patch("core.autonomy.execute_or_request",
               return_value={"status": "pending_approval", "action_id": "AB12CD34"}) as gate:
        out = act.run_action(plan, "legal_intake")
    kw = gate.call_args.kwargs
    assert kw["action_type"] == "send_email" and kw["channel"] == "email"
    assert kw["target"] == "boss@acme.com" and kw["role"] == "legal_intake"
    assert out["status"] == "pending_approval" and out["action_id"] == "AB12CD34"


def test_describe_action_variants():
    assert "waiting for owner approval (id AB12CD34)" in act.describe_action(
        {"status": "pending_approval", "tool": "send_slack", "target": "slack", "action_id": "AB12CD34"})
    assert "Action done" in act.describe_action({"status": "executed", "tool": "send_slack", "detail": "Slack 'slack': sent"})
    assert "could not be completed" in act.describe_action({"status": "executed", "tool": "send_slack", "detail": "Slack 'x': failed"})
    assert "not taken" in act.describe_action({"status": "skipped", "tool": "send_slack", "detail": "autonomy off"})
    assert "could not be completed" in act.describe_action({"status": "error", "tool": "send_slack"})


def test_maybe_act_none_and_runs():
    with patch.object(act, "plan_action", return_value=None), patch.object(act, "run_action") as run:
        assert act.maybe_act("q", "a", MagicMock(), None) is None
    run.assert_not_called()
    plan = {"tool": "send_slack", "channel": "slack", "target": "slack", "content": "c", "subject": ""}
    with patch.object(act, "plan_action", return_value=plan), \
         patch.object(act, "run_action", return_value={"status": "skipped"}) as run:
        assert act.maybe_act("q", "a", MagicMock(), "support") == {"status": "skipped"}
    run.assert_called_once_with(plan, "support")
