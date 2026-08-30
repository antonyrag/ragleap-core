"""
Tests for core/integrations/snowflake_connector.py -- the Snowflake connector.
snowflake-connector-python is a heavy optional dependency that isn't
installed in CI (matching the pymysql/psycopg2 pattern in
sql_connectors.py -- these are lazily imported, not required deps).
We inject a fake `snowflake.connector` module into sys.modules so the
connector's lazy `import snowflake.connector` succeeds against a
MagicMock, and drive behavior by configuring that mock per test.
"""
import os
import sys
import json
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Inject fake snowflake.connector module before importing the connector,
# so its lazy `import snowflake.connector` resolves to our mock.
_fake_connector_module = MagicMock()
_fake_snowflake_pkg = MagicMock()
_fake_snowflake_pkg.connector = _fake_connector_module
sys.modules['snowflake'] = _fake_snowflake_pkg
sys.modules['snowflake.connector'] = _fake_connector_module

from core.integrations.snowflake_connector import SnowflakeConnector
from core.integrations.base import DataSource

VALID_CONN = json.dumps({
    "account": "abc123", "user": "bot", "password": "secret",
    "warehouse": "wh1", "database": "db1", "schema": "public",
})


@pytest.fixture(autouse=True)
def reset_connect_mock():
    _fake_connector_module.connect.reset_mock(return_value=True, side_effect=True)
    yield


def test_missing_connection_string_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string=None)
    ok, msg = SnowflakeConnector(ds).test_connection()
    assert ok is False
    assert "connection_string" in msg


def test_invalid_json_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string="not json")
    ok, msg = SnowflakeConnector(ds).test_connection()
    assert ok is False
    assert "JSON" in msg


def test_missing_required_keys_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string='{"account": "abc"}')
    ok, msg = SnowflakeConnector(ds).test_connection()
    assert ok is False
    assert "missing required keys" in msg


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string=VALID_CONN)
    mock_conn = MagicMock()
    _fake_connector_module.connect.return_value = mock_conn
    ok, msg = SnowflakeConnector(ds).test_connection()
    assert ok is True
    assert "successful" in msg
    mock_conn.close.assert_called_once()


def test_fetch_data_requires_query_template():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string=VALID_CONN, query_template=None)
    _fake_connector_module.connect.return_value = MagicMock()
    with pytest.raises(ValueError, match="query_template"):
        SnowflakeConnector(ds).fetch_data()


def test_fetch_data_maps_columns():
    ds = DataSource(
        id="1", name="test", source_type="snowflake", connection_string=VALID_CONN,
        query_template="SELECT * FROM t",
    )
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("ID",), ("NAME",)]
    mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
    mock_conn.cursor.return_value = mock_cursor
    _fake_connector_module.connect.return_value = mock_conn
    data = SnowflakeConnector(ds).fetch_data()
    assert data == [{"ID": 1, "NAME": "Alice"}, {"ID": 2, "NAME": "Bob"}]


def test_fetch_data_substitutes_user_identifier():
    ds = DataSource(
        id="1", name="test", source_type="snowflake", connection_string=VALID_CONN,
        query_template="SELECT * FROM t WHERE id = {{user_id}}",
    )
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("ID",)]
    mock_cursor.fetchall.return_value = [(1,)]
    mock_conn.cursor.return_value = mock_cursor
    _fake_connector_module.connect.return_value = mock_conn
    SnowflakeConnector(ds).fetch_data(user_identifier="42")
    called_query, called_params = mock_cursor.execute.call_args.args
    assert "%s" in called_query
    assert called_params == ["42"]


def test_connection_failure_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="snowflake", connection_string=VALID_CONN)
    _fake_connector_module.connect.side_effect = Exception("account locked")
    ok, msg = SnowflakeConnector(ds).test_connection()
    assert ok is False
    assert "account locked" in msg
