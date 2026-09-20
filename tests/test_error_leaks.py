"""Regression tests: raw exception text must never reach API callers (CodeQL py/stack-trace-exposure)."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import autonomy, observability
from core import generation as gen
from core.generation import GenerationService

SECRET = "SECRET-KEY-abc quota project 123"


def _failing_conn():
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = Exception(SECRET)
    return conn


def test_generate_answer_failure_does_not_leak_error_text():
    s = object.__new__(GenerationService)
    s.primary_config = {"provider": "testprovider", "api_key": "x", "model": "m", "base_url": None}
    s.provider = "testprovider"
    with patch.object(s, "_call_provider", side_effect=Exception(SECRET)):
        r = s.generate_answer("q?", [{"document_name": "d", "content": "c"}])
    assert r["provider_used"] is None
    assert r["answer"] == gen.GENERIC_FAILURE_MESSAGE
    assert "SECRET" not in r["answer"] and "quota" not in r["answer"]


def test_execute_or_request_error_does_not_leak():
    settings = {"mode": "full", "channels": [], "actions": [], "approval_channel": "telegram", "approval_target": ""}
    with patch.object(autonomy, "get_autonomy_settings", return_value=settings), \
         patch.object(autonomy, "log_autonomous_action"):
        r = autonomy.execute_or_request("x", "slack", "t", "c", execute_fn=MagicMock(side_effect=Exception(SECRET)))
    assert r["status"] == "error" and "SECRET" not in str(r)


def test_autonomy_daily_report_does_not_leak():
    with patch.object(autonomy, "get_connection", return_value=_failing_conn()):
        out = autonomy.generate_autonomy_daily_report()
    assert "SECRET" not in out and "error" in out.lower()


def test_rejection_report_does_not_leak():
    with patch.object(autonomy, "get_connection", return_value=_failing_conn()):
        out = autonomy.generate_rejection_pattern_report()
    assert "SECRET" not in out and "error" in out.lower()


def test_observability_report_does_not_leak():
    with patch.object(observability, "get_connection", return_value=_failing_conn()):
        out = observability.generate_observability_report()
    assert "SECRET" not in out and "error" in out.lower()


def test_streaming_paths_do_not_interpolate_exception_text():
    root = os.path.join(os.path.dirname(__file__), "..")
    api_src = open(os.path.join(root, "core", "api.py")).read()
    gen_src = open(os.path.join(root, "core", "generation.py")).read()
    assert "[Error: {exc}]" not in api_src
    assert "yield f\"\\n[Error: generation interrupted" not in gen_src
    assert "GENERIC_FAILURE_MESSAGE" in gen_src


def test_api_http_errors_do_not_interpolate_exception_text():
    root = os.path.join(os.path.dirname(__file__), "..")
    src = open(os.path.join(root, "core", "api.py")).read()
    for label in ("Ingestion failed", "Chat failed", "Failed to create integration",
                  "Failed to create CSV data source"):
        assert f'detail=f"{label}: {{exc}}"' not in src, label
    assert "detail=f" not in "".join(l for l in src.split("\n") if "{exc}" in l)


def test_send_via_channel_exception_does_not_leak():
    from core import action_senders
    with patch.object(action_senders, "send_slack", side_effect=Exception(SECRET)):
        out = autonomy._send_via_channel("slack", "x", "hi")
    assert "SECRET" not in out and "quota" not in out and "sent" not in out


def test_sync_endpoint_failure_returns_fresh_generic_dict():
    from core.api import sync_integration, integrations_service
    with patch.object(integrations_service, "sync_data_source",
                      return_value={"success": False, "error": SECRET, "extra": "internal"}), \
         patch.object(integrations_service, "get_data_source", return_value=None):
        result = sync_integration("ds-1")
    assert result == {"success": False, "error": "Sync failed. See server logs for details."}


def test_sync_endpoint_success_returns_only_known_fields():
    from core.api import sync_integration, integrations_service
    with patch.object(integrations_service, "sync_data_source",
                      return_value={"success": True, "records_synced": 3, "debug": "x"}), \
         patch.object(integrations_service, "get_data_source", return_value=None):
        result = sync_integration("ds-1")
    assert result == {"success": True, "records_synced": 3}


def test_api_does_not_copy_result_dict_on_sync_failure():
    root = os.path.join(os.path.dirname(__file__), "..")
    assert "{**result" not in open(os.path.join(root, "core", "api.py")).read()
