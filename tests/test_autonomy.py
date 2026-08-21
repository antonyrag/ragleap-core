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
