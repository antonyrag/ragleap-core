"""
Tests for core/integrations/razorpay_connector.py -- the Razorpay REST API connector.
Pure unit tests against a mocked requests.get; no live Razorpay account
or DB needed.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.integrations.razorpay_connector import RazorpayConnector
from core.integrations.base import DataSource


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_missing_credentials_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint=None, api_key=None)
    ok, msg = RazorpayConnector(ds).test_connection()
    assert ok is False
    assert "api_endpoint" in msg and "api_key" in msg


def test_missing_key_secret_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key=None)
    ok, msg = RazorpayConnector(ds).test_connection()
    assert ok is False


def test_connection_success():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE")
    with patch("core.integrations.razorpay_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"items": []})
        ok, msg = RazorpayConnector(ds).test_connection()
    assert ok is True
    assert "successful" in msg


def test_razorpay_api_error_surfaces_message():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE")
    with patch("core.integrations.razorpay_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(401, {"error": {"description": "Authentication failed"}})
        ok, msg = RazorpayConnector(ds).test_connection()
    assert ok is False
    assert "Authentication failed" in msg


def test_fetch_payments_default():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE")
    with patch("core.integrations.razorpay_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"items": [{"id": "pay_1", "amount": 500}]})
        data = RazorpayConnector(ds).fetch_data()
    assert data == [{"id": "pay_1", "amount": 500}]


def test_fetch_paginates_using_skip():
    ds = DataSource(id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE")
    full_page = _mock_response(200, {"items": [{"id": f"pay_{i}"} for i in range(100)]})
    partial_page = _mock_response(200, {"items": [{"id": "pay_100"}]})
    with patch("core.integrations.razorpay_connector.requests.get") as mock_get:
        mock_get.side_effect = [full_page, partial_page]
        data = RazorpayConnector(ds).fetch_data()
    assert len(data) == 101
    assert mock_get.call_count == 2


def test_fetch_orders_resource():
    ds = DataSource(
        id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE",
        query_template="orders",
    )
    with patch("core.integrations.razorpay_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"items": [{"id": "order_1"}]})
        data = RazorpayConnector(ds).fetch_data()
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/orders")
    assert data == [{"id": "order_1"}]


def test_unsupported_query_template_raises():
    ds = DataSource(
        id="1", name="test", source_type="razorpay", api_endpoint="rzp_test_123", api_key="secretFAKE",
        query_template="bogus",
    )
    with pytest.raises(ValueError, match="Unsupported Razorpay query_template"):
        RazorpayConnector(ds).fetch_data()
