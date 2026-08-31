"""
BigQuery connector for RagLeap Core integrations.

Uses the google-cloud-bigquery library, lazily imported (optional
dependency) -- same graceful-ImportError pattern as SnowflakeConnector/
MySQLConnector/PostgreSQLConnector, since BigQuery is a real SQL
warehouse rather than a REST API.

Field usage:
    connection_string -> the full GCP service account JSON key (as a string)
    api_endpoint       -> optional GCP project ID override (if omitted,
                          uses the project_id embedded in the service
                          account JSON)
    query_template     -> the SQL query to run. Use {{user_id}} or
                          {{user_identifier}} as a placeholder -- it's
                          converted to a proper BigQuery named query
                          parameter (@user_identifier) rather than raw
                          string substitution, to avoid SQL injection.
"""
import json
import logging
from typing import Dict, Any, Tuple, List

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)


class BigQueryConnector(BaseDatabaseConnector):
    """BigQuery connector using google-cloud-bigquery (service account JSON auth)."""

    def _parse_credentials(self) -> Dict[str, Any]:
        raw = (self.data_source.connection_string or '').strip()
        if not raw:
            raise ValueError(
                "BigQuery connector requires connection_string as the full "
                "GCP service account JSON key"
            )
        try:
            creds_dict = json.loads(raw)
        except Exception:
            raise ValueError("BigQuery connector's connection_string must be valid JSON")
        if not creds_dict.get('project_id') and not (self.data_source.api_endpoint or '').strip():
            raise ValueError(
                "BigQuery connector requires a project_id -- either in the "
                "service account JSON or via api_endpoint"
            )
        return creds_dict

    def _client(self):
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
        except ImportError:
            raise ImportError(
                "google-cloud-bigquery not installed. Run: pip install google-cloud-bigquery"
            )
        creds_dict = self._parse_credentials()
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        project_id = (self.data_source.api_endpoint or '').strip() or creds_dict.get('project_id')
        return bigquery.Client(credentials=credentials, project=project_id)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            client = self._client()
            list(client.list_datasets(max_results=1))
            return True, "BigQuery connection successful"
        except ImportError as e:
            return False, str(e)
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"BigQuery connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            from google.cloud import bigquery
        except ImportError:
            raise ImportError(
                "google-cloud-bigquery not installed. Run: pip install google-cloud-bigquery"
            )
        client = self._client()

        query = (self.data_source.query_template or '').strip()
        if not query:
            raise ValueError("BigQuery connector requires query_template (SQL query)")

        job_config = None
        if user_identifier:
            query = query.replace('{{user_id}}', '@user_identifier').replace(
                '{{user_identifier}}', '@user_identifier'
            )
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("user_identifier", "STRING", user_identifier)]
            )

        try:
            query_job = client.query(query, job_config=job_config)
            rows = query_job.result()
            return [dict(row.items()) for row in rows]
        except Exception as e:
            logger.error(f"BigQueryConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            client = self._client()
        except Exception as e:
            return {'tables': [], 'filtered_count': 0, 'error': str(e)}
        try:
            allowed = []
            filtered_count = 0
            total = 0
            for dataset in client.list_datasets():
                for table in client.list_tables(dataset.dataset_id):
                    total += 1
                    table_name = f"{dataset.dataset_id}.{table.table_id}"
                    if self._is_table_blacklisted(table.table_id):
                        filtered_count += 1
                        continue
                    allowed.append({'name': table_name, 'columns': []})
            return {
                'tables': allowed,
                'total_tables': total,
                'filtered_count': filtered_count,
                'db_type': 'bigquery',
            }
        except Exception as e:
            return {'tables': [], 'filtered_count': 0, 'error': str(e)}

    def execute_query(self, query: str) -> List[Dict]:
        original = self.data_source.query_template
        self.data_source.query_template = query
        try:
            return self.fetch_data()
        finally:
            self.data_source.query_template = original
