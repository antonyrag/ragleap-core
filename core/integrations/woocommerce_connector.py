"""
WooCommerce connector for RagLeap Core integrations.

Uses the WooCommerce REST API (v3) directly over HTTP (requests) --
same lightweight approach as the other connectors, no woocommerce SDK
dependency. Auth is HTTP Basic (consumer_key:consumer_secret), per
WooCommerce's own REST API convention when the store isn't served
over HTTPS with query-param auth -- Basic Auth works for both.

Field usage:
    api_endpoint    -> store base URL (e.g. https://mystore.com,
                       no trailing slash, no /wp-json suffix)
    api_key         -> Consumer Key (ck_...)
    connection_string -> Consumer Secret (cs_...)
    query_template  -> resource type: 'orders' (default), 'products',
                       'customers', 'coupons', or 'refunds'
"""
import logging
from typing import Dict, List, Tuple

import requests
from requests.auth import HTTPBasicAuth

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

WC_API_VERSION = "wc/v3"

RESOURCE_ENDPOINTS = {
    'orders': 'orders',
    'products': 'products',
    'customers': 'customers',
    'coupons': 'coupons',
    'refunds': 'products/refunds',
}


class WooCommerceConnector(BaseDatabaseConnector):
    """Connector for WooCommerce stores using the REST API v3 (Consumer Key/Secret)."""

    def _base_url(self) -> str:
        store_url = (self.data_source.api_endpoint or '').strip().rstrip('/')
        if not store_url:
            raise ValueError("WooCommerce connector requires api_endpoint (store base URL)")
        return f"{store_url}/wp-json/{WC_API_VERSION}"

    def _auth(self) -> HTTPBasicAuth:
        consumer_key = (self.data_source.api_key or '').strip()
        consumer_secret = (self.data_source.connection_string or '').strip()
        if not consumer_key or not consumer_secret:
            raise ValueError(
                "WooCommerce connector requires api_key (Consumer Key) and "
                "connection_string (Consumer Secret)"
            )
        return HTTPBasicAuth(consumer_key, consumer_secret)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            base_url = self._base_url()
            auth = self._auth()
            resp = requests.get(f"{base_url}/orders", auth=auth, params={"per_page": 1}, timeout=15)
            if resp.status_code == 200:
                return True, "WooCommerce connection successful"
            try:
                err = resp.json().get("message", resp.text)
            except Exception:
                err = resp.text
            return False, f"WooCommerce API error ({resp.status_code}): {err}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"WooCommerce connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        base_url = self._base_url()
        auth = self._auth()
        resource = (self.data_source.query_template or 'orders').strip().lower() or 'orders'
        path = RESOURCE_ENDPOINTS.get(resource)
        if not path:
            raise ValueError(
                f"Unsupported WooCommerce query_template: {resource}. "
                f"Use one of: {', '.join(sorted(RESOURCE_ENDPOINTS.keys()))}."
            )

        items = []
        page = 1
        try:
            while True:
                resp = requests.get(
                    f"{base_url}/{path}",
                    auth=auth,
                    params={"per_page": 100, "page": page},
                    timeout=30,
                )
                if resp.status_code != 200:
                    try:
                        err = resp.json().get("message", resp.text)
                    except Exception:
                        err = resp.text
                    raise ValueError(f"WooCommerce API error ({resp.status_code}): {err}")
                batch = resp.json()
                if not isinstance(batch, list) or not batch:
                    break
                items.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            if user_identifier:
                items = [
                    i for i in items
                    if str(i.get("customer_id", "")) == str(user_identifier)
                    or str(i.get("id", "")) == str(user_identifier)
                ]
            return items
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"WooCommerceConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict:
        tables = [{'name': r, 'label': r.title(), 'columns': []} for r in RESOURCE_ENDPOINTS]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
