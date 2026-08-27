"""
Tests for core/integrations/slack_connector.py — the Slack Web API connector.
Pure unit tests against a mocked requests.get; no live Slack workspace or
DB needed (unlike test_autonomy.py, this connector talks to an external
API, not Postgres, so there's nothing to fixture-reset).
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.integrations.slack_connector import SlackConnector
from core.integrations.base import DataSource


def _mock_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def test_missing_token_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="slack", api_key=None)
    ok, msg = SlackConnector(ds).test_connection()
    assert ok is False
    assert "api_key" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake")
    with patch("core.integrations.slack_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"ok": True, "team": "TestCo", "user": "ragleap-bot"})
        ok, msg = SlackConnector(ds).test_connection()
    assert ok is True
    assert "TestCo" in msg


def test_slack_api_error_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake")
    with patch("core.integrations.slack_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"ok": False, "error": "invalid_auth"})
        ok, msg = SlackConnector(ds).test_connection()
    assert ok is False
    assert "invalid_auth" in msg


def test_fetch_channels_default():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake")
    with patch("core.integrations.slack_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"ok": True, "channels": [{"id": "C1", "name": "general"}]})
        data = SlackConnector(ds).fetch_data()
    assert data == [{"id": "C1", "name": "general"}]


def test_fetch_users():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake", query_template="users")
    with patch("core.integrations.slack_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"ok": True, "members": [{"id": "U1", "name": "alice"}]})
        data = SlackConnector(ds).fetch_data()
    assert data == [{"id": "U1", "name": "alice"}]


def test_fetch_messages_requires_channel_id():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake", query_template="messages")
    with pytest.raises(ValueError, match="api_endpoint"):
        SlackConnector(ds).fetch_data()


def test_fetch_messages_filters_by_user():
    ds = DataSource(
        id="1", name="test", source_type="slack", api_key="xoxb-fake",
        query_template="messages", api_endpoint="C123",
    )
    with patch("core.integrations.slack_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response({
            "ok": True,
            "messages": [{"user": "U1", "text": "hi"}, {"user": "U2", "text": "hey"}],
        })
        data = SlackConnector(ds).fetch_data(user_identifier="U1")
    assert data == [{"user": "U1", "text": "hi"}]


def test_unsupported_query_template_raises():
    ds = DataSource(id="1", name="test", source_type="slack", api_key="xoxb-fake", query_template="bogus")
    with pytest.raises(ValueError, match="Unsupported Slack query_template"):
        SlackConnector(ds).fetch_data()
