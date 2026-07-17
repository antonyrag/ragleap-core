"""
Generic REST API connector for RagLeap Core integrations.
Ported from production's api/addon_services.py — logic unchanged.
"""
import logging
import requests
from typing import Dict, List, Tuple

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)


class RestAPIConnector(BaseDatabaseConnector):
    """REST API connector"""

    def test_connection(self) -> Tuple[bool, str]:
        try:
            endpoint = self.data_source.api_endpoint
            headers = self.data_source.api_headers or {}

            if self.data_source.api_key:
                headers['Authorization'] = f'Bearer {self.data_source.api_key}'

            response = requests.get(endpoint, headers=headers, timeout=10)

            if response.status_code == 200:
                return True, "Connection successful"
            else:
                return False, f"API returned status {response.status_code}"

        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            endpoint = self.data_source.api_endpoint
            headers = self.data_source.api_headers or {}

            if self.data_source.api_key:
                headers['Authorization'] = f'Bearer {self.data_source.api_key}'

            if user_identifier:
                endpoint = endpoint.replace('{{user_id}}', user_identifier)
                endpoint = endpoint.replace('{{user_identifier}}', user_identifier)

            response = requests.get(endpoint, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ['data', 'results', 'items', 'records']:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return [data]

            return []

        except Exception as e:
            logger.error(f"REST API fetch error: {e}")
            raise
