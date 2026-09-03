"""
Tests for core/integrations/gmail_connector.py -- the Gmail connector.
google-api-python-client / google-auth are heavy optional dependencies
not installed in CI (same convention as snowflake-connector-python /
google-cloud-bigquery). We inject fake googleapiclient.discovery and
google.oauth2.credentials modules into sys.modules so the connector's
lazy imports succeed against MagicMocks.
"""
import os
import sys
import json
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_fake_discovery_module = MagicMock()
_fake_googleapiclient_pkg = MagicMock()
_fake_googleapiclient_pkg.discovery = _fake_discovery_module
sys.modules['googleapiclient'] = _fake_googleapiclient_pkg
sys.modules['googleapiclient.discovery'] = _fake_discovery_module

_fake_credentials_module = MagicMock()
_fake_oauth2_pkg = MagicMock()
_fake_oauth2_pkg.credentials = _fake_credentials_module
_fake_google_pkg = MagicMock()
_fake_google_pkg.oauth2 = _fake_oauth2_pkg
sys.modules['google'] = _fake_google_pkg
sys.modules['google.oauth2'] = _fake_oauth2_pkg
sys.modules['google.oauth2.credentials'] = _fake_credentials_module

from core.integrations.gmail_connector import GmailConnector
from core.integrations.base import DataSource

VALID_CONN = json.dumps({
    "client_id": "abc.apps.googleusercontent.com",
    "client_secret": "secret",
    "refresh_token": "1//refresh-token",
})


@pytest.fixture(autouse=True)
def reset_mocks():
    _fake_discovery_module.reset_mock(return_value=True, side_effect=True)
    _fake_credentials_module.reset_mock(return_value=True, side_effect=True)
    yield


def test_missing_connection_string_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string=None)
    ok, msg = GmailConnector(ds).test_connection()
    assert ok is False
    assert "connection_string" in msg


def test_invalid_json_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string="not json")
    ok, msg = GmailConnector(ds).test_connection()
    assert ok is False
    assert "JSON" in msg


def test_missing_required_keys_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string='{"client_id": "abc"}')
    ok, msg = GmailConnector(ds).test_connection()
    assert ok is False
    assert "missing required keys" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string=VALID_CONN)
    mock_service = MagicMock()
    mock_service.users().getProfile().execute.return_value = {"emailAddress": "me@example.com"}
    _fake_discovery_module.build.return_value = mock_service
    ok, msg = GmailConnector(ds).test_connection()
    assert ok is True
    assert "me@example.com" in msg


def test_connection_failure_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string=VALID_CONN)
    _fake_discovery_module.build.side_effect = Exception("invalid_grant")
    ok, msg = GmailConnector(ds).test_connection()
    assert ok is False
    assert "invalid_grant" in msg


def test_fetch_data_maps_messages():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string=VALID_CONN)
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1", "threadId": "t1"}]
    }
    mock_service.users().messages().get().execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Hello there",
        "payload": {"headers": [
            {"name": "Subject", "value": "Test Subject"},
            {"name": "From", "value": "alice@example.com"},
            {"name": "Date", "value": "Mon, 1 Jan 2024 00:00:00 +0000"},
        ]},
    }
    _fake_discovery_module.build.return_value = mock_service
    data = GmailConnector(ds).fetch_data()
    assert data == [{
        "id": "m1", "threadId": "t1", "snippet": "Hello there",
        "subject": "Test Subject", "from": "alice@example.com",
        "date": "Mon, 1 Jan 2024 00:00:00 +0000",
    }]


def test_fetch_data_no_messages_returns_empty_list():
    ds = DataSource(id="1", name="test", source_type="gmail", connection_string=VALID_CONN)
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {}
    _fake_discovery_module.build.return_value = mock_service
    data = GmailConnector(ds).fetch_data()
    assert data == []


def test_fetch_data_appends_user_identifier_to_query():
    ds = DataSource(
        id="1", name="test", source_type="gmail", connection_string=VALID_CONN,
        query_template="is:unread",
    )
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {}
    _fake_discovery_module.build.return_value = mock_service
    GmailConnector(ds).fetch_data(user_identifier="from:bob@example.com")
    list_call_kwargs = mock_service.users().messages().list.call_args.kwargs
    assert list_call_kwargs["q"] == "is:unread from:bob@example.com"
