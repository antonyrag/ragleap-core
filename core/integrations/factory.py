"""
Connector factory for RagLeap Core integrations.
Ported from production's DatabaseConnector.get_connector().
"""
from core.integrations.base import BaseDatabaseConnector, DataSource
from core.integrations.sql_connectors import MySQLConnector, PostgreSQLConnector
from core.integrations.mongodb import MongoDBConnector
from core.integrations.rest_api import RestAPIConnector
from core.integrations.crm_connectors import (
    SalesforceConnector,
    HubSpotConnector,
    ShopifyConnector,
    GoogleSheetsConnector,
    StripeConnector,
)

CONNECTOR_MAP = {
    'mysql': MySQLConnector,
    'postgresql': PostgreSQLConnector,
    'mongodb': MongoDBConnector,
    'rest_api': RestAPIConnector,
    'salesforce': SalesforceConnector,
    'hubspot': HubSpotConnector,
    'shopify': ShopifyConnector,
    'google_sheets': GoogleSheetsConnector,
    'stripe': StripeConnector,
}


def get_connector(data_source: DataSource) -> BaseDatabaseConnector:
    """Get the appropriate connector for a data source."""
    connector_class = CONNECTOR_MAP.get(data_source.source_type)
    if not connector_class:
        raise ValueError(
            f"Unsupported source type: {data_source.source_type}. "
            f"Supported types: {', '.join(sorted(CONNECTOR_MAP.keys()))}"
        )
    return connector_class(data_source)
