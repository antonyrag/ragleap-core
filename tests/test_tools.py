"""
Tests for core/employees/tools.py - the Tool registry.
Requires a Postgres DB with db/schema.sql applied, reachable via the
DATABASE_URL env var (same convention as tests/test_autonomy.py), since
escalate_to_owner's handler dispatches through
core.autonomy.execute_or_request().
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import autonomy
from core.employees._db import get_connection
from core.employees.tools import TOOL_REGISTRY, Tool


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


def test_registry_has_escalate_to_owner():
    assert "escalate_to_owner" in TOOL_REGISTRY
    tool = TOOL_REGISTRY["escalate_to_owner"]
    assert isinstance(tool, Tool)
    assert tool.name == "escalate_to_owner"
    assert callable(tool.handler)
    assert tool.requires_approval is True


def test_escalate_to_owner_parameters_schema_present():
    tool = TOOL_REGISTRY["escalate_to_owner"]
    assert set(tool.parameters.keys()) == {"channel", "target", "message_text"}


def test_escalate_to_owner_returns_none_when_no_escalation_detected():
    tool = TOOL_REGISTRY["escalate_to_owner"]
    result = tool.handler(channel="telegram", target="123", message_text="what's the return policy?")
    assert result is None


def test_escalate_to_owner_dispatches_and_off_mode_skips():
    autonomy.set_autonomy(mode="off")
    tool = TOOL_REGISTRY["escalate_to_owner"]
    result = tool.handler(channel="telegram", target="123", message_text="I want to talk to a human")
    assert result is not None
    assert result["status"] == "skipped"
    assert result["result"] == "autonomy off"


def test_escalate_to_owner_dispatches_and_semi_mode_creates_pending():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    tool = TOOL_REGISTRY["escalate_to_owner"]
    result = tool.handler(channel="telegram", target="999", message_text="let me speak to a person")
    assert result is not None
    assert result["status"] == "pending_approval"
    assert len(result["action_id"]) == 8
