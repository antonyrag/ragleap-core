"""
Gmail connector for RagLeap Core integrations.

Uses the Gmail API via google-api-python-client + google-auth, lazily
imported (optional dependency) -- same graceful-ImportError pattern as
SnowflakeConnector/BigQueryConnector.

Unlike every other connector, Gmail's API requires OAuth2 rather than
a static key. Per RagLeap's BYOK design (Discussion #169 -- "never an
OAuth app RagLeap owns"), this connector does NOT perform an OAuth
consent flow itself. The user brings their own OAuth client
(registered in their own Google Cloud project) and a refresh_token
they've already obtained once (e.g. via Google's OAuth Playground or
a short one-time script) -- the connector only ever exchanges that
refresh_token for short-lived access tokens.

Field usage:
    connection_string -> JSON: {"client_id": "...", "client_secret": "...",
                                 "refresh_token": "..."}
    query_template     -> optional Gmail search query (same syntax as the
                          Gmail search box, e.g. "is:unread from:x@y.com");
                          blank fetches the most recent messages
"""
import json
import logging
from typing import Dict, Any, Tuple, List

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

REQUIRED_CONN_KEYS = ['client_id', 'client_secret', 'refresh_token']
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailConnector(BaseDatabaseConnector):
    """Gmail connector using the Gmail API (OAuth2 refresh token, BYO OAuth client)."""

    def _parse_conn(self) -> Dict[str, str]:
        raw = (self.data_source.connection_string or '').strip()
        if not raw:
            raise ValueError(
                "Gmail connector requires connection_string as JSON: "
                '{"client_id": "...", "client_secret": "...", "refresh_token": "..."}'
            )
        try:
            params = json.loads(raw)
        except Exception:
            raise ValueError("Gmail connector's connection_string must be valid JSON")
        missing = [k for k in REQUIRED_CONN_KEYS if not params.get(k)]
        if missing:
            raise ValueError(f"Gmail connection_string missing required keys: {', '.join(missing)}")
        return params

    def _service(self):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "google-api-python-client / google-auth not installed. "
                "Run: pip install google-api-python-client google-auth"
            )
        params = self._parse_conn()
        credentials = Credentials(
            token=None,
            refresh_token=params['refresh_token'],
            client_id=params['client_id'],
            client_secret=params['client_secret'],
            token_uri=TOKEN_URI,
        )
        return build('gmail', 'v1', credentials=credentials, cache_discovery=False)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            service = self._service()
            profile = service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', 'unknown')
            return True, f"Gmail connected: {email}"
        except ImportError as e:
            return False, str(e)
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Gmail connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        service = self._service()
        query = (self.data_source.query_template or '').strip()
        if user_identifier:
            query = f"{query} {user_identifier}".strip()

        try:
            list_resp = service.users().messages().list(
                userId='me', q=query or None, maxResults=50
            ).execute()
            message_refs = list_resp.get('messages', [])

            results = []
            for ref in message_refs:
                msg = service.users().messages().get(
                    userId='me', id=ref['id'], format='metadata',
                    metadataHeaders=['Subject', 'From', 'Date'],
                ).execute()
                headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                results.append({
                    'id': msg.get('id'),
                    'threadId': msg.get('threadId'),
                    'snippet': msg.get('snippet', ''),
                    'subject': headers.get('Subject', ''),
                    'from': headers.get('From', ''),
                    'date': headers.get('Date', ''),
                })
            return results
        except Exception as e:
            logger.error(f"GmailConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        return {
            'tables': [{'name': 'messages', 'label': 'Messages', 'columns': []}],
            'filtered_count': 0,
            'message': (
                'Gmail exposes a single logical "messages" resource, '
                'filterable via query_template (Gmail search syntax)'
            ),
        }

    def execute_query(self, query: str) -> List[Dict]:
        original = self.data_source.query_template
        self.data_source.query_template = query
        try:
            return self.fetch_data()
        finally:
            self.data_source.query_template = original
