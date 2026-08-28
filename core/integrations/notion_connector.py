"""
Notion connector for RagLeap Core integrations.

Uses the Notion API directly over HTTP (requests) — same lightweight
approach as SlackConnector/RestAPIConnector, no notion-client dependency.

Field usage:
    api_key         -> Notion Integration Token (Internal Integration Secret)
    api_endpoint    -> database ID (for query_template='database') or
                       page ID (for query_template='page'); ignored for 'search'
    query_template  -> 'database' (default, queries a database), 'page'
                       (fetch a page's block children), or 'search'
"""
import logging
from typing import Dict, List, Tuple

import requests

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionConnector(BaseDatabaseConnector):
    """Connector for Notion workspaces using the Notion API (Integration token)."""

    def _headers(self) -> Dict[str, str]:
        token = (self.data_source.api_key or '').strip()
        if not token:
            raise ValueError("Notion connector requires api_key (Internal Integration Secret)")
        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, json_body: Dict = None) -> Dict:
        resp = requests.request(method, f"{NOTION_API_BASE}{path}", headers=self._headers(), json=json_body, timeout=15)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("message", resp.text)
            except Exception:
                err = resp.text
            raise ValueError(f"Notion API error ({resp.status_code}): {err}")
        return resp.json()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            data = self._call("GET", "/users/me")
            name = data.get("name") or data.get("bot", {}).get("owner", {}).get("type", "unknown")
            return True, f"Notion connected: {name}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Notion connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        resource = (self.data_source.query_template or 'database').strip().lower() or 'database'
        try:
            if resource == 'database':
                database_id = (self.data_source.api_endpoint or '').strip()
                if not database_id:
                    raise ValueError("Notion 'database' fetch requires api_endpoint (database ID)")
                data = self._call("POST", f"/databases/{database_id}/query", {})
                return data.get("results", [])
            elif resource == 'page':
                page_id = (self.data_source.api_endpoint or '').strip()
                if not page_id:
                    raise ValueError("Notion 'page' fetch requires api_endpoint (page ID)")
                data = self._call("GET", f"/blocks/{page_id}/children")
                return data.get("results", [])
            elif resource == 'search':
                data = self._call("POST", "/search", {})
                return data.get("results", [])
            else:
                raise ValueError(
                    f"Unsupported Notion query_template: {resource}. Use 'database', 'page', or 'search'."
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"NotionConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict:
        resources = ['database', 'page', 'search']
        tables = [{'name': r, 'label': r.title(), 'columns': []} for r in resources]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
