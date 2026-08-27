"""
Slack connector for RagLeap Core integrations.

Uses Slack's Web API directly over HTTP (requests) rather than the
slack_sdk package — consistent with RestAPIConnector's approach and
avoids adding a new dependency for what is a plain bearer-token REST API.

Field usage:
    api_key         -> Bot User OAuth Token (starts with xoxb-)
    api_endpoint    -> channel ID to fetch messages from (required only
                       when query_template='messages')
    query_template  -> resource type: 'channels' (default), 'users', or 'messages'
"""
import logging
from typing import Dict, List, Tuple

import requests

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackConnector(BaseDatabaseConnector):
    """Connector for Slack workspaces using the Slack Web API (Bot token)."""

    def _headers(self) -> Dict[str, str]:
        token = (self.data_source.api_key or '').strip()
        if not token:
            raise ValueError("Slack connector requires api_key (Bot User OAuth Token, starts with xoxb-)")
        return {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, params: Dict = None) -> Dict:
        resp = requests.get(f"{SLACK_API_BASE}/{method}", headers=self._headers(), params=params or {}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise ValueError(f"Slack API error ({method}): {data.get('error', 'unknown_error')}")
        return data

    def test_connection(self) -> Tuple[bool, str]:
        try:
            data = self._call("auth.test")
            team = data.get("team", "unknown workspace")
            user = data.get("user", "unknown bot")
            return True, f"Slack connected: {user} in {team}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Slack connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        resource = (self.data_source.query_template or 'channels').strip().lower() or 'channels'
        try:
            if resource == 'channels':
                data = self._call("conversations.list", {"limit": 200, "types": "public_channel,private_channel"})
                return data.get("channels", [])
            elif resource == 'users':
                data = self._call("users.list", {"limit": 200})
                return data.get("members", [])
            elif resource == 'messages':
                channel_id = (self.data_source.api_endpoint or '').strip()
                if not channel_id:
                    raise ValueError("Slack 'messages' fetch requires api_endpoint (channel ID)")
                data = self._call("conversations.history", {"channel": channel_id, "limit": 200})
                messages = data.get("messages", [])
                if user_identifier:
                    messages = [m for m in messages if m.get("user") == user_identifier]
                return messages
            else:
                raise ValueError(
                    f"Unsupported Slack query_template: {resource}. Use 'channels', 'users', or 'messages'."
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"SlackConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict:
        resources = ['channels', 'users', 'messages']
        tables = [{'name': r, 'label': r.title(), 'columns': []} for r in resources]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
