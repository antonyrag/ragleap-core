"""
Tests for core/integrations/notion_connector.py — the Notion API connector.
Pure unit tests against a mocked requests.request; no live Notion
workspace or DB needed.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.integrations.notion_connector import NotionConnector
from core.integrations.base import DataSource


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_missing_token_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="notion", api_key=None)
    ok, msg = NotionConnector(ds).test_connection()
    assert ok is False
    assert "api_key" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake")
    with patch("core.integrations.notion_connector.requests.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"name": "RagLeap Bot"})
        ok, msg = NotionConnector(ds).test_connection()
    assert ok is True
    assert "RagLeap Bot" in msg


def test_notion_api_error_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake")
    with patch("core.integrations.notion_connector.requests.request") as mock_req:
        mock_req.return_value = _mock_response(401, {"message": "API token is invalid."})
        ok, msg = NotionConnector(ds).test_connection()
    assert ok is False
    assert "API token is invalid." in msg


def test_fetch_database_default():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake", api_endpoint="db123")
    with patch("core.integrations.notion_connector.requests.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"results": [{"id": "row1"}]})
        data = NotionConnector(ds).fetch_data()
    assert data == [{"id": "row1"}]


def test_fetch_database_requires_endpoint():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake")
    with pytest.raises(ValueError, match="api_endpoint"):
        NotionConnector(ds).fetch_data()


def test_fetch_page():
    ds = DataSource(
        id="1", name="test", source_type="notion", api_key="secret_fake",
        query_template="page", api_endpoint="page123",
    )
    with patch("core.integrations.notion_connector.requests.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"results": [{"id": "block1"}]})
        data = NotionConnector(ds).fetch_data()
    assert data == [{"id": "block1"}]


def test_fetch_search_no_endpoint_needed():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake", query_template="search")
    with patch("core.integrations.notion_connector.requests.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"results": [{"id": "page1"}, {"id": "db1"}]})
        data = NotionConnector(ds).fetch_data()
    assert len(data) == 2


def test_unsupported_query_template_raises():
    ds = DataSource(id="1", name="test", source_type="notion", api_key="secret_fake", query_template="bogus")
    with pytest.raises(ValueError, match="Unsupported Notion query_template"):
        NotionConnector(ds).fetch_data()
