"""
Tests for core/integrations/airtable_connector.py -- the Airtable Web API connector.
Pure unit tests against a mocked requests.get; no live Airtable base or
DB needed.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.integrations.airtable_connector import AirtableConnector
from core.integrations.base import DataSource


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_missing_token_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key=None, api_endpoint="app123/Tasks")
    ok, msg = AirtableConnector(ds).test_connection()
    assert ok is False
    assert "api_key" in msg


def test_missing_endpoint_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE")
    ok, msg = AirtableConnector(ds).test_connection()
    assert ok is False
    assert "api_endpoint" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE", api_endpoint="app123/Tasks")
    with patch("core.integrations.airtable_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"records": []})
        ok, msg = AirtableConnector(ds).test_connection()
    assert ok is True
    assert "app123" in msg and "Tasks" in msg


def test_airtable_api_error_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE", api_endpoint="app123/Tasks")
    with patch("core.integrations.airtable_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(401, {"error": {"message": "Invalid authentication token"}})
        ok, msg = AirtableConnector(ds).test_connection()
    assert ok is False
    assert "Invalid authentication token" in msg


def test_fetch_flattens_fields():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE", api_endpoint="app123/Tasks")
    with patch("core.integrations.airtable_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {
            "records": [{"id": "rec1", "fields": {"Name": "Task A", "Done": False}}]
        })
        data = AirtableConnector(ds).fetch_data()
    assert data == [{"id": "rec1", "Name": "Task A", "Done": False}]


def test_fetch_paginates_using_offset():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE", api_endpoint="app123/Tasks")
    page1 = _mock_response(200, {
        "records": [{"id": "rec1", "fields": {"Name": "A"}}],
        "offset": "itrOFFSET",
    })
    page2 = _mock_response(200, {
        "records": [{"id": "rec2", "fields": {"Name": "B"}}],
    })
    with patch("core.integrations.airtable_connector.requests.get") as mock_get:
        mock_get.side_effect = [page1, page2]
        data = AirtableConnector(ds).fetch_data()
    assert data == [{"id": "rec1", "Name": "A"}, {"id": "rec2", "Name": "B"}]
    assert mock_get.call_count == 2


def test_fetch_uses_filter_formula_when_query_template_set():
    ds = DataSource(
        id="1", name="test", source_type="airtable", api_key="patFAKE",
        api_endpoint="app123/Tasks", query_template="{Done}=TRUE()",
    )
    with patch("core.integrations.airtable_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"records": []})
        AirtableConnector(ds).fetch_data()
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["filterByFormula"] == "{Done}=TRUE()"


def test_fetch_bad_endpoint_format_raises():
    ds = DataSource(id="1", name="test", source_type="airtable", api_key="patFAKE", api_endpoint="app123-no-slash")
    with pytest.raises(ValueError, match="api_endpoint"):
        AirtableConnector(ds).fetch_data()
