"""
Tests for core/integrations/woocommerce_connector.py -- the WooCommerce REST API v3 connector.
Pure unit tests against a mocked requests.get; no live WooCommerce
store or DB needed.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.integrations.woocommerce_connector import WooCommerceConnector
from core.integrations.base import DataSource


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_missing_store_url_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="woocommerce", api_endpoint=None)
    ok, msg = WooCommerceConnector(ds).test_connection()
    assert ok is False
    assert "api_endpoint" in msg


def test_missing_credentials_fails_gracefully():
    ds = DataSource(id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com", api_key=None)
    ok, msg = WooCommerceConnector(ds).test_connection()
    assert ok is False
    assert "api_key" in msg or "connection_string" in msg


def test_connection_success():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake",
    )
    with patch("core.integrations.woocommerce_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, [])
        ok, msg = WooCommerceConnector(ds).test_connection()
    assert ok is True
    assert "successful" in msg


def test_woocommerce_api_error_surfaces_message():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake",
    )
    with patch("core.integrations.woocommerce_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(401, {"message": "Consumer key is invalid."})
        ok, msg = WooCommerceConnector(ds).test_connection()
    assert ok is False
    assert "Consumer key is invalid." in msg


def test_fetch_orders_default():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake",
    )
    with patch("core.integrations.woocommerce_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, [{"id": 1, "status": "processing"}])
        data = WooCommerceConnector(ds).fetch_data()
    assert data == [{"id": 1, "status": "processing"}]


def test_fetch_paginates_using_page_param():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake",
    )
    full_page = _mock_response(200, [{"id": i} for i in range(100)])
    partial_page = _mock_response(200, [{"id": 100}])
    with patch("core.integrations.woocommerce_connector.requests.get") as mock_get:
        mock_get.side_effect = [full_page, partial_page]
        data = WooCommerceConnector(ds).fetch_data()
    assert len(data) == 101
    assert mock_get.call_count == 2


def test_fetch_products_resource():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake", query_template="products",
    )
    with patch("core.integrations.woocommerce_connector.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, [{"id": 5, "name": "Widget"}])
        data = WooCommerceConnector(ds).fetch_data()
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/products")
    assert data == [{"id": 5, "name": "Widget"}]


def test_unsupported_query_template_raises():
    ds = DataSource(
        id="1", name="test", source_type="woocommerce", api_endpoint="https://store.com",
        api_key="ck_fake", connection_string="cs_fake", query_template="bogus",
    )
    with pytest.raises(ValueError, match="Unsupported WooCommerce query_template"):
        WooCommerceConnector(ds).fetch_data()
