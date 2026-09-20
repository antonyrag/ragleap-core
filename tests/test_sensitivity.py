"""Tests for core/employees/sensitivity.py and its use in ask() and the autonomy gate. No network; DB reads mocked."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import autonomy, chat
from core.employees import defaults as d
from core.employees import roles as employee_roles
from core.employees.sensitivity import is_sensitive_role


def _row(role=None, display_name="", tags=()):
    return {"role": role, "display_name": display_name, "skill_tags": list(tags)}


def _env(**kw):
    return patch.dict(os.environ, kw)


def test_builtin_sensitive_roles_are_sensitive_without_db():
    with patch.object(employee_roles, "get_role", side_effect=Exception("no db")) as g:
        for r in d.SENSITIVE_DOMAIN_ROLES:
            assert is_sensitive_role(r) is True
    g.assert_not_called()


def test_builtin_non_sensitive_roles_stay_non_sensitive_without_db():
    with patch.object(employee_roles, "get_role") as g:
        for r in ("sales", "support", "manager", "warranty_claims_agent", "returns_refunds_agent"):
            assert is_sensitive_role(r) is False, r
    g.assert_not_called()


def test_none_and_empty_role():
    assert is_sensitive_role(None) is False and is_sensitive_role("") is False


def test_runtime_role_sensitive_by_name_tokens():
    with patch.object(employee_roles, "get_role", return_value=None):
        for r in ("tax_lawyer_bot", "Medical-Intake", "immigration helper", "clinical_notes_agent"):
            assert is_sensitive_role(r) is True, r


def test_runtime_role_sensitive_by_tags_or_display_name():
    with patch.object(employee_roles, "get_role", return_value=_row("x", tags=["faq", "legal"])):
        assert is_sensitive_role("x") is True
    with patch.object(employee_roles, "get_role", return_value=_row("x", display_name="Health Coach")):
        assert is_sensitive_role("x") is True


def test_benign_runtime_roles_and_whole_word_matching():
    with patch.object(employee_roles, "get_role", return_value=_row("pizza_bot", tags=["menu", "orders"])):
        assert is_sensitive_role("pizza_bot") is False
    with patch.object(employee_roles, "get_role", return_value=None):
        for r in ("taxonomy_bot", "healthy_recipes", "lawn_care_agent"):
            assert is_sensitive_role(r) is False, r


def test_env_extra_forces_sensitive():
    with patch.object(employee_roles, "get_role", return_value=None), _env(SENSITIVE_ROLES_EXTRA="pizza_bot, Sales"):
        assert is_sensitive_role("pizza_bot") is True
        assert is_sensitive_role("sales") is True


def test_env_reviewed_safe_exempts_runtime_roles_but_never_builtin_sensitive():
    with patch.object(employee_roles, "get_role", return_value=None), \
         _env(SENSITIVE_ROLES_REVIEWED_SAFE="tax_reminder_bot,legal_intake,healthcare_intake"):
        assert is_sensitive_role("tax_reminder_bot") is False
        assert is_sensitive_role("legal_intake") is True
        assert is_sensitive_role("healthcare_intake") is True


def test_db_error_falls_back_to_name_only_and_never_raises():
    with patch.object(employee_roles, "get_role", side_effect=Exception("db down")):
        assert is_sensitive_role("tax_bot") is True
        assert is_sensitive_role("pizza_bot") is False


def test_unexpected_failure_fails_closed():
    with patch("core.employees.sensitivity._builtin_names", side_effect=Exception("boom")), \
         patch.object(employee_roles, "get_role", return_value=None):
        assert is_sensitive_role("anything_at_all") is True


def test_markers_are_a_superset_of_the_static_guard_markers():
    from tests.test_role_definitions import SENSITIVE_MARKER_TAGS
    assert SENSITIVE_MARKER_TAGS <= __import__("core.employees.sensitivity", fromlist=["x"]).SENSITIVE_MARKERS


def _settings(mode="full"):
    return {"mode": mode, "channels": [], "actions": [], "approval_channel": "telegram", "approval_target": ""}


def test_autonomy_forces_runtime_sensitive_role_from_full_to_semi():
    fn = MagicMock()
    with patch.object(employee_roles, "get_role", return_value=None), \
         patch.object(autonomy, "get_autonomy_settings", return_value=_settings()), \
         patch.object(autonomy, "get_connection", return_value=MagicMock()), \
         patch.object(autonomy, "request_approval", return_value=True), \
         patch.object(autonomy, "log_autonomous_action"):
        r = autonomy.execute_or_request("x", "slack", "t", "c", execute_fn=fn, role="tax_lawyer_bot")
    assert r["status"] == "pending_approval"
    fn.assert_not_called()


def test_autonomy_still_executes_for_benign_runtime_role():
    fn = MagicMock(return_value="ok")
    with patch.object(employee_roles, "get_role", return_value=_row("pizza_bot", tags=["menu"])), \
         patch.object(autonomy, "get_autonomy_settings", return_value=_settings()), \
         patch.object(autonomy, "log_autonomous_action"):
        r = autonomy.execute_or_request("x", "slack", "t", "c", execute_fn=fn, role="pizza_bot")
    assert r["status"] == "executed"
    fn.assert_called_once()


def _ask(role):
    gen = MagicMock()
    gen.return_value.generate_answer.return_value = {
        "answer": "a", "sources": [], "provider_used": "gemini", "usage": {}, "chunks_sent": 1,
        "fallback_used": False, "reasoning": None,
    }
    gen.return_value.check_grounding.return_value = None
    with patch.object(chat, "_prepare", return_value=([{"document_name": "d"}], "en", False)), \
         patch.object(chat, "GenerationService", gen), \
         patch.object(employee_roles, "get_role", return_value=None), \
         patch.object(chat, "_build_system_prompt", return_value=(None, [])), \
         patch.object(chat, "_augment_query_with_reminder", return_value="q?"), \
         patch.object(chat, "record_trace"):
        chat.ask("q?", role=role)
    return gen.return_value


def test_ask_runtime_sensitive_role_gets_reasoning_and_grounding_check():
    g = _ask("tax_helper_bot")
    assert g.generate_answer.call_args.kwargs["reasoning_mode"] is True
    g.check_grounding.assert_called_once()


def test_ask_benign_runtime_role_gets_neither():
    g = _ask("pizza_bot")
    assert g.generate_answer.call_args.kwargs["reasoning_mode"] is False
    g.check_grounding.assert_not_called()
