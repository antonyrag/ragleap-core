"""
Airtable connector for RagLeap Core integrations.

Uses the Airtable Web API directly over HTTP (requests) -- same
lightweight approach as SlackConnector/NotionConnector, no pyairtable
dependency.

Field usage:
    api_key         -> Airtable Personal Access Token
    api_endpoint    -> "<base_id>/<table_name_or_id>" (both required,
                       slash-separated -- e.g. "appXXXXXXXX/Tasks")
    query_template  -> optional Airtable formula (filterByFormula);
                       leave blank to fetch all records
"""
import logging
from typing import Dict, List, Tuple

import requests

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

AIRTABLE_API_BASE = "https://api.airtable.com/v0"


class AirtableConnector(BaseDatabaseConnector):
    """Connector for Airtable bases using the Airtable Web API (Personal Access Token)."""

    def _headers(self) -> Dict[str, str]:
        token = (self.data_source.api_key or '').strip()
        if not token:
            raise ValueError("Airtable connector requires api_key (Personal Access Token)")
        return {"Authorization": f"Bearer {token}"}

    def _parse_endpoint(self):
        endpoint = (self.data_source.api_endpoint or '').strip().strip('/')
        if not endpoint or '/' not in endpoint:
            raise ValueError(
                "Airtable connector requires api_endpoint as '<base_id>/<table_name_or_id>'"
            )
        base_id, table = endpoint.split('/', 1)
        if not base_id or not table:
            raise ValueError(
                "Airtable connector requires api_endpoint as '<base_id>/<table_name_or_id>'"
            )
        return base_id, table

    def test_connection(self) -> Tuple[bool, str]:
        try:
            base_id, table = self._parse_endpoint()
            resp = requests.get(
                f"{AIRTABLE_API_BASE}/{base_id}/{table}",
                headers=self._headers(),
                params={"maxRecords": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, f"Airtable connected: base {base_id}, table {table}"
            try:
                err = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err = resp.text
            return False, f"Airtable API error ({resp.status_code}): {err}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Airtable connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        base_id, table = self._parse_endpoint()
        formula = (self.data_source.query_template or '').strip()

        records = []
        params = {"pageSize": 100}
        if formula:
            params["filterByFormula"] = formula

        offset = None
        try:
            while True:
                if offset:
                    params["offset"] = offset
                resp = requests.get(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table}",
                    headers=self._headers(),
                    params=params,
                    timeout=30,
                )
                if resp.status_code != 200:
                    try:
                        err = resp.json().get("error", {}).get("message", resp.text)
                    except Exception:
                        err = resp.text
                    raise ValueError(f"Airtable API error ({resp.status_code}): {err}")
                data = resp.json()
                for rec in data.get("records", []):
                    flat = {"id": rec.get("id")}
                    flat.update(rec.get("fields", {}))
                    records.append(flat)
                offset = data.get("offset")
                if not offset:
                    break
            return records
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"AirtableConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict:
        return {'tables': [], 'filtered_count': 0, 'message': 'Set api_endpoint to <base_id>/<table_name> to fetch records'}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
