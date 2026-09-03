"""
Tests for core/autonomy.py - the single-tenant Autonomous Loop.
Requires a Postgres DB with db/schema.sql applied, reachable via the
DATABASE_URL env var (same convention as core/employees/_db.py).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import autonomy
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def clean_autonomy_tables():
    """Reset autonomy tables before each test so tests do not interfere."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM autonomy_settings")
        cur.execute("DELETE FROM autonomy_pending")
        cur.execute("DELETE FROM autonomy_log")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


def test_default_settings_are_off():
    settings = autonomy.get_autonomy_settings()
    assert settings["mode"] == "off"
    assert settings["channels"] == []
    assert settings["actions"] == []


def test_set_and_get_settings_roundtrip():
    ok = autonomy.set_autonomy(
        mode="semi",
        channels=["telegram"],
        actions=["followup"],
        approval_channel="telegram",
        approval_target="12345",
    )
    assert ok is True

    settings = autonomy.get_autonomy_settings()
    assert settings["mode"] == "semi"
    assert settings["channels"] == ["telegram"]
    assert settings["actions"] == ["followup"]
    assert settings["approval_target"] == "12345"


def test_off_mode_skips_everything():
    autonomy.set_autonomy(mode="off")
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert result["result"] == "autonomy off"


def test_action_allowlist_blocks_disallowed_action():
    autonomy.set_autonomy(mode="full", actions=["reply"], channels=[])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert "not in allowed actions" in result["result"]


def test_channel_allowlist_blocks_disallowed_channel():
    autonomy.set_autonomy(mode="full", actions=[], channels=["discord"])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert "not in allowed channels" in result["result"]


def test_full_mode_executes_via_custom_fn_and_logs():
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "custom result"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute,
    )
    assert result["status"] == "executed"
    assert result["result"] == "custom result"
    assert called["ran"] is True

    report = autonomy.generate_autonomy_daily_report()
    assert "followup" in report


def test_semi_mode_creates_pending_and_approval_flow():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="999", content="test message"
    )
    assert result["status"] == "pending_approval"
    action_id = result["action_id"]
    assert len(action_id) == 8

    reply = autonomy.process_approval_response(f"NO {action_id}")
    assert reply is not None
    assert "rejected" in reply.lower()


def test_process_approval_response_ignores_non_approval_messages():
    reply = autonomy.process_approval_response("What are your business hours?")
    assert reply is None


def test_process_approval_response_unknown_id():
    reply = autonomy.process_approval_response("YES ZZZZZZZZ")
    assert reply is not None
    assert "not found" in reply.lower()


def test_sensitive_role_forces_full_to_semi():
    """core.employees.defaults.SENSITIVE_DOMAIN_ROLES enforcement: a role
    in that set must never execute directly even when general mode is
    'full' -- it should be forced down to the approval flow instead."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "should not run"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute, role="legal_intake",
    )
    assert result["status"] == "pending_approval"
    assert "ran" not in called, "sensitive-domain role executed directly in full mode -- guardrail not enforced"


def test_non_sensitive_role_full_mode_executes_normally():
    """A role NOT in SENSITIVE_DOMAIN_ROLES should behave exactly like
    the no-role case -- full mode executes directly, no forced downgrade."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "custom result"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute, role="sales",
    )
    assert result["status"] == "executed"
    assert called["ran"] is True


def test_role_is_persisted_in_autonomy_log():
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=lambda: "ok", role="support",
    )
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_log ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "support"


def test_role_is_persisted_through_semi_approval_flow():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="999",
        content="test message", role="healthcare_intake",
    )
    assert result["status"] == "pending_approval"
    action_id = result["action_id"]

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_pending WHERE action_id = %s", (action_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "healthcare_intake"

    reply = autonomy.process_approval_response(f"NO {action_id}")
    assert reply is not None

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_log ORDER BY id DESC LIMIT 1")
        log_row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert log_row is not None
    assert log_row[0] == "healthcare_intake"


def test_role_optional_backward_compatible():
    """Existing callers that never pass role must keep working exactly
    as before -- role stays None throughout, nothing breaks."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=lambda: "ok",
    )
    assert result["status"] == "executed"
