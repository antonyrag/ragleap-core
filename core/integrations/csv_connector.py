"""
CSV connector for RagLeap Core integrations.
Content is stored directly in Postgres (data_sources.csv_content) rather
than on disk — the app container has no persistent volume mount, so a
file saved to the container filesystem would be lost on the next
`docker compose up --build`.
"""
import csv
import io
import logging
from typing import Dict, List, Tuple

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)


class CSVConnector(BaseDatabaseConnector):
    """CSV connector — reads rows from CSV content stored in the database."""

    def test_connection(self) -> Tuple[bool, str]:
        content = self.data_source.csv_content
        if not content:
            return False, "No CSV content stored for this data source."
        try:
            reader = csv.DictReader(io.StringIO(content))
            headers = reader.fieldnames
            if not headers:
                return False, "CSV content has no header row."
            next(reader, None)  # confirm at least one row is parseable
            return True, f"CSV readable with columns: {', '.join(headers)}"
        except Exception as e:
            return False, f"Failed to parse CSV content: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        content = self.data_source.csv_content
        if not content:
            raise ValueError("No CSV content stored for this data source.")

        records = []
        try:
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                if user_identifier:
                    id_field = self.data_source.user_identifier_field
                    if str(row.get(id_field, '')).strip() != str(user_identifier):
                        continue
                records.append(dict(row))
        except Exception as e:
            logger.error(f"CSV parse error: {e}")
            raise

        return records
