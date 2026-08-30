"""
Snowflake connector for RagLeap Core integrations.

Uses the snowflake-connector-python library, lazily imported (optional
dependency) -- same graceful-ImportError pattern as MySQLConnector/
PostgreSQLConnector in sql_connectors.py, since Snowflake is a real
SQL database rather than a REST API.

Field usage:
    connection_string -> JSON: {"account": "...", "user": "...", "password": "...",
                                 "warehouse": "...", "database": "...", "schema": "..."}
                          (account/user/password required; the rest optional)
    query_template     -> the SQL query to run (same {{user_id}} /
                          {{user_identifier}} substitution convention
                          as MySQLConnector/PostgreSQLConnector)
"""
import json
import logging
from typing import Dict, Any, Tuple, List

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)

REQUIRED_CONN_KEYS = ['account', 'user', 'password']


class SnowflakeConnector(BaseDatabaseConnector):
    """Snowflake connector using snowflake-connector-python."""

    def _parse_conn(self) -> Dict[str, str]:
        raw = (self.data_source.connection_string or '').strip()
        if not raw:
            raise ValueError(
                "Snowflake connector requires connection_string as JSON: "
                '{"account": "...", "user": "...", "password": "...", '
                '"warehouse": "...", "database": "...", "schema": "..."}'
            )
        try:
            params = json.loads(raw)
        except Exception:
            raise ValueError("Snowflake connector's connection_string must be valid JSON")
        missing = [k for k in REQUIRED_CONN_KEYS if not params.get(k)]
        if missing:
            raise ValueError(f"Snowflake connection_string missing required keys: {', '.join(missing)}")
        return params

    def _connect(self):
        try:
            import snowflake.connector
        except ImportError:
            raise ImportError(
                "snowflake-connector-python not installed. Run: pip install snowflake-connector-python"
            )
        params = self._parse_conn()
        return snowflake.connector.connect(
            account=params['account'],
            user=params['user'],
            password=params['password'],
            warehouse=params.get('warehouse'),
            database=params.get('database'),
            schema=params.get('schema'),
            login_timeout=10,
        )

    def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = self._connect()
            conn.close()
            return True, "Snowflake connection successful"
        except ImportError as e:
            return False, str(e)
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Snowflake connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        conn = self._connect()
        try:
            query = (self.data_source.query_template or '').strip()
            if not query:
                raise ValueError("Snowflake connector requires query_template (SQL query)")

            params = None
            if user_identifier:
                query = query.replace('{{user_id}}', '%s').replace('{{user_identifier}}', '%s')
                params = [user_identifier] * query.count('%s')

            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            finally:
                cursor.close()
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"SnowflakeConnector.fetch_data error: {e}")
            raise
        finally:
            conn.close()

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            conn = self._connect()
        except Exception as e:
            return {'tables': [], 'filtered_count': 0, 'error': str(e)}
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("SHOW TABLES")
                all_tables = [row[1] for row in cursor.fetchall()]
                allowed = []
                filtered_count = 0
                for table in all_tables:
                    if self._is_table_blacklisted(table):
                        filtered_count += 1
                        continue
                    allowed.append({'name': table, 'columns': []})
                return {
                    'tables': allowed,
                    'total_tables': len(all_tables),
                    'filtered_count': filtered_count,
                    'db_type': 'snowflake',
                }
            finally:
                cursor.close()
        except Exception as e:
            return {'tables': [], 'filtered_count': 0, 'error': str(e)}
        finally:
            conn.close()

    def execute_query(self, query: str) -> List[Dict]:
        original = self.data_source.query_template
        self.data_source.query_template = query
        try:
            return self.fetch_data()
        finally:
            self.data_source.query_template = original
