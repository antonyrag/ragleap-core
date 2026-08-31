"""
Tests for core/integrations/bigquery_connector.py -- the BigQuery connector.
google-cloud-bigquery is a heavy optional dependency not installed in
CI (same convention as snowflake-connector-python for
SnowflakeConnector). We inject fake google.cloud.bigquery and
google.oauth2.service_account modules into sys.modules so the
connector's lazy imports succeed against MagicMocks.
"""
import os
import sys
import json
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_fake_bigquery_module = MagicMock()
_fake_cloud_pkg = MagicMock()
_fake_cloud_pkg.bigquery = _fake_bigquery_module
_fake_google_pkg = MagicMock()
_fake_google_pkg.cloud = _fake_cloud_pkg
sys.modules['google'] = _fake_google_pkg
sys.modules['google.cloud'] = _fake_cloud_pkg
sys.modules['google.cloud.bigquery'] = _fake_bigquery_module

_fake_service_account_module = MagicMock()
_fake_oauth2_pkg = MagicMock()
_fake_oauth2_pkg.service_account = _fake_service_account_module
_fake_google_pkg.oauth2 = _fake_oauth2_pkg
sys.modules['google.oauth2'] = _fake_oauth2_pkg
sys.modules['google.oauth2.service_account'] = _fake_service_account_module

from core.integrations.bigquery_connector import BigQueryConnector
from core.integrations.base import DataSource

VALID_CREDS = json.dumps({
    "type": "service_account", "project_id": "my-project",
    "client_email": "bot@my-project.iam.gserviceaccount.com",
})


@pytest.fixture(autouse=True)
def reset_mocks():
    _fake_bigquery_module.reset_mock()
    _fake_service_account_module.reset_mock()
    yield


def test_missing_connection_string_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string=None)
    ok, msg = BigQueryConnector(ds).test_connection()
    assert ok is False
    assert "connection_string" in msg


def test_invalid_json_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string="not json")
    ok, msg = BigQueryConnector(ds).test_connection()
    assert ok is False
    assert "JSON" in msg


def test_missing_project_id_without_override_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string='{"type": "service_account"}')
    ok, msg = BigQueryConnector(ds).test_connection()
    assert ok is False
    assert "project_id" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string=VALID_CREDS)
    mock_client = MagicMock()
    mock_client.list_datasets.return_value = []
    _fake_bigquery_module.Client.return_value = mock_client
    ok, msg = BigQueryConnector(ds).test_connection()
    assert ok is True
    assert "successful" in msg


def test_fetch_data_requires_query_template():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string=VALID_CREDS, query_template=None)
    _fake_bigquery_module.Client.return_value = MagicMock()
    with pytest.raises(ValueError, match="query_template"):
        BigQueryConnector(ds).fetch_data()


def test_fetch_data_maps_rows():
    ds = DataSource(
        id="1", name="test", source_type="bigquery", connection_string=VALID_CREDS,
        query_template="SELECT * FROM t",
    )
    mock_client = MagicMock()
    mock_row1 = MagicMock()
    mock_row1.items.return_value = [("id", 1), ("name", "Alice")]
    mock_row2 = MagicMock()
    mock_row2.items.return_value = [("id", 2), ("name", "Bob")]
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [mock_row1, mock_row2]
    mock_client.query.return_value = mock_query_job
    _fake_bigquery_module.Client.return_value = mock_client
    data = BigQueryConnector(ds).fetch_data()
    assert data == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]


def test_fetch_data_uses_named_parameter_for_user_identifier():
    ds = DataSource(
        id="1", name="test", source_type="bigquery", connection_string=VALID_CREDS,
        query_template="SELECT * FROM t WHERE id = {{user_id}}",
    )
    mock_client = MagicMock()
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = []
    mock_client.query.return_value = mock_query_job
    _fake_bigquery_module.Client.return_value = mock_client
    BigQueryConnector(ds).fetch_data(user_identifier="42")
    called_query = mock_client.query.call_args.args[0]
    assert "@user_identifier" in called_query
    assert "{{user_id}}" not in called_query
    _fake_bigquery_module.ScalarQueryParameter.assert_called_once_with("user_identifier", "STRING", "42")


def test_connection_failure_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="bigquery", connection_string=VALID_CREDS)
    _fake_bigquery_module.Client.side_effect = Exception("permission denied")
    ok, msg = BigQueryConnector(ds).test_connection()
    assert ok is False
    assert "permission denied" in msg
