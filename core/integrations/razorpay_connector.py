"""
Razorpay connector for RagLeap Core integrations.

Uses the Razorpay REST API directly over HTTP (requests) -- same
lightweight approach as SlackConnector/NotionConnector/AirtableConnector,
no razorpay SDK dependency. Auth is HTTP Basic (key_id:key_secret),
per Razorpay's own API convention -- unlike the other connectors,
this needs both an ID and a secret, so api_endpoint carries the key_id
and api_key carries the key_secret.

Field usage:
    api_endpoint    -> Razorpay Key ID (starts with rzp_)
    api_key         -> Razorpay Key Secret
    query_template  -> resource type: 'payments' (default), 'orders',
                       'refunds', 'customers', or 'settlements'
"""
import logging
from typing import Dict, List, Tuple

import requests
from requests.auth import HTTPBasicAuth

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

RESOURCE_ENDPOINTS = {
    'payments': 'payments',
    'orders': 'orders',
    'refunds': 'refunds',
    'customers': 'customers',
    'settlements': 'settlements',
}


class RazorpayConnector(BaseDatabaseConnector):
    """Connector for Razorpay using the REST API (Key ID / Key Secret Basic Auth)."""

    def _auth(self) -> HTTPBasicAuth:
        key_id = (self.data_source.api_endpoint or '').strip()
        key_secret = (self.data_source.api_key or '').strip()
        if not key_id or not key_secret:
            raise ValueError(
                "Razorpay connector requires api_endpoint (Key ID) and api_key (Key Secret)"
            )
        return HTTPBasicAuth(key_id, key_secret)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            auth = self._auth()
            resp = requests.get(
                f"{RAZORPAY_API_BASE}/payments",
                auth=auth,
                params={"count": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "Razorpay connection successful"
            try:
                err = resp.json().get("error", {}).get("description", resp.text)
            except Exception:
                err = resp.text
            return False, f"Razorpay API error ({resp.status_code}): {err}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Razorpay connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        auth = self._auth()
        resource = (self.data_source.query_template or 'payments').strip().lower() or 'payments'
        path = RESOURCE_ENDPOINTS.get(resource)
        if not path:
            raise ValueError(
                f"Unsupported Razorpay query_template: {resource}. "
                f"Use one of: {', '.join(sorted(RESOURCE_ENDPOINTS.keys()))}."
            )

        items = []
        params = {"count": 100, "skip": 0}
        try:
            while True:
                resp = requests.get(f"{RAZORPAY_API_BASE}/{path}", auth=auth, params=params, timeout=30)
                if resp.status_code != 200:
                    try:
                        err = resp.json().get("error", {}).get("description", resp.text)
                    except Exception:
                        err = resp.text
                    raise ValueError(f"Razorpay API error ({resp.status_code}): {err}")
                data = resp.json()
                batch = data.get("items", [])
                items.extend(batch)
                if len(batch) < params["count"]:
                    break
                params["skip"] += params["count"]
            if user_identifier:
                items = [i for i in items if i.get("customer_id") == user_identifier or i.get("id") == user_identifier]
            return items
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"RazorpayConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict:
        tables = [{'name': r, 'label': r.title(), 'columns': []} for r in RESOURCE_ENDPOINTS]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
