"""
CRM / SaaS connectors for RagLeap Core integrations: Salesforce, HubSpot,
Shopify, Google Sheets, Stripe. Ported from production's
api/addon_services.py — logic unchanged. All use BYOK credentials the
user provides directly (username/password/token, private-app token,
admin API token, service-account JSON, or secret key) — none require a
RagLeap-owned OAuth app registration.
"""
import logging
from datetime import date
from typing import Dict, Any, Tuple, List

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)


class SalesforceConnector(BaseDatabaseConnector):
    """
    Connector for Salesforce CRM using the simple_salesforce library.
    Credentials (3 options):
    Option A (recommended): username+password+security_token stored in connection_string as JSON
        {"username":"user@co.com","password":"pass","security_token":"TOKEN","domain":"login"}
        -> Permanent, never expires
    Option B: api_key=access_token + api_endpoint=instance_url (OAuth2, expires every 2h)
    Option C: connection_string stores JSON with instance_url + access_token
    """

    def _get_client(self):
        try:
            from simple_salesforce import Salesforce
        except ImportError:
            raise ImportError("simple_salesforce not installed. Run: pip install simple-salesforce")

        try:
            import json as _json
            creds = _json.loads(self.data_source.connection_string or '{}')
            username = creds.get('username', '')
            password = creds.get('password', '')
            security_token = creds.get('security_token', '')
            domain = creds.get('domain', 'login')
            if username and password:
                return Salesforce(
                    username=username, password=password,
                    security_token=security_token, domain=domain
                )
        except Exception:
            pass

        instance_url = (self.data_source.api_endpoint or '').rstrip('/')
        access_token = (self.data_source.api_key or '').strip()
        if not instance_url or not access_token:
            try:
                import json as _json
                creds = _json.loads(self.data_source.connection_string or '{}')
                instance_url = creds.get('instance_url', instance_url)
                access_token = creds.get('access_token', access_token)
            except Exception:
                pass
        if instance_url and access_token:
            return Salesforce(instance_url=instance_url, session_id=access_token)

        raise ValueError(
            "Salesforce requires username+password in connection_string JSON "
            "or api_endpoint+api_key for OAuth token."
        )

    def test_connection(self) -> Tuple[bool, str]:
        try:
            sf = self._get_client()
            sf.describe()
            return True, "Salesforce connection successful"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Salesforce connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            sf = self._get_client()
            query = (self.data_source.query_template or '').strip()
            if not query:
                return []
            result = sf.query_all(query)
            records = result.get('records', [])
            return [{k: v for k, v in r.items() if k != 'attributes'} for r in records]
        except Exception as e:
            logger.error(f"SalesforceConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            sf = self._get_client()
            desc = sf.describe()
            sobjects = desc.get('sobjects', [])
            tables = []
            for obj in sobjects[:50]:
                name = obj.get('name', '')
                if self._is_table_blacklisted(name):
                    continue
                tables.append({'name': name, 'label': obj.get('label', name), 'columns': []})
            return {'tables': tables, 'filtered_count': max(0, len(sobjects) - len(tables))}
        except Exception as e:
            return {'error': str(e), 'tables': [], 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        sf = self._get_client()
        result = sf.query_all(query)
        records = result.get('records', [])
        return [{k: v for k, v in r.items() if k != 'attributes'} for r in records]


class HubSpotConnector(BaseDatabaseConnector):
    """
    Connector for HubSpot CRM using the hubspot-api-client library.
    api_key stores the Private App access token.
    """

    def _get_client(self):
        try:
            from hubspot import HubSpot
        except ImportError:
            raise ImportError("hubspot-api-client not installed. Run: pip install hubspot-api-client")

        token = (self.data_source.api_key or '').strip()
        if not token:
            raise ValueError("HubSpot connector requires api_key (Private App access token)")
        return HubSpot(access_token=token)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            client = self._get_client()
            client.crm.contacts.basic_api.get_page(limit=1)
            return True, "HubSpot connection successful"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"HubSpot connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            client = self._get_client()
            object_type = (self.data_source.query_template or 'contacts').strip() or 'contacts'
            api = getattr(client.crm, object_type, None)
            if api is None:
                return []
            page = api.basic_api.get_page(limit=100)
            return [r.to_dict() for r in (page.results or [])]
        except Exception as e:
            logger.error(f"HubSpotConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        objects = ['contacts', 'companies', 'deals', 'tickets', 'products', 'line_items']
        tables = [{'name': obj, 'label': obj.title(), 'columns': []} for obj in objects]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()


class ShopifyConnector(BaseDatabaseConnector):
    """
    Connector for Shopify stores using the ShopifyAPI library.
    api_endpoint stores the shop URL (e.g. mystore.myshopify.com),
    api_key stores the Admin API access token.
    """

    def _setup_session(self):
        try:
            import shopify
        except ImportError:
            raise ImportError("ShopifyAPI not installed. Run: pip install ShopifyAPI")

        shop_url = (self.data_source.api_endpoint or '').strip().rstrip('/')
        token = (self.data_source.api_key or '').strip()
        if not shop_url or not token:
            raise ValueError("Shopify connector requires api_endpoint (shop URL) and api_key (access token)")

        try:
            import shopify as _shopify
            api_version = _shopify.ApiVersion.STABLE_SHOPIFY_API_VERSION
        except Exception:
            y = date.today().year
            q = (date.today().month - 1) // 3
            quarters = ['01', '04', '07', '10']
            api_version = f"{y}-{quarters[max(q-1,0)]}"
        session = shopify.Session(shop_url, api_version, token)
        shopify.ShopifyResource.activate_session(session)
        return shopify

    def test_connection(self) -> Tuple[bool, str]:
        try:
            shopify = self._setup_session()
            shop = shopify.Shop.current()
            return True, f"Shopify connected: {shop.name}"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Shopify connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            shopify = self._setup_session()
            resource_name = (self.data_source.query_template or 'Order').strip() or 'Order'
            resource_class = getattr(shopify, resource_name, None)
            if resource_class is None:
                return []
            items = resource_class.find(limit=250)
            return [item.to_dict() for item in items]
        except Exception as e:
            logger.error(f"ShopifyConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        resources = ['Order', 'Product', 'Customer', 'Variant', 'Collection',
                     'DraftOrder', 'Fulfillment', 'Refund', 'Transaction']
        tables = [{'name': r, 'label': r, 'columns': []} for r in resources]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()


class GoogleSheetsConnector(BaseDatabaseConnector):
    """
    Connector for Google Sheets using the gspread library.
    connection_string stores JSON service-account credentials (as a JSON string),
    api_endpoint stores the spreadsheet URL or ID,
    query_template stores the worksheet name (default: first sheet).
    """

    def _get_client(self):
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError:
            raise ImportError("gspread not installed. Run: pip install gspread")

        creds_json = (self.data_source.connection_string or '').strip()
        if not creds_json:
            raise ValueError("Google Sheets connector requires connection_string (service account JSON)")

        import json as _json
        creds_dict = _json.loads(creds_json)
        scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            gc = self._get_client()
            spreadsheet_id = (self.data_source.api_endpoint or '').strip()
            if spreadsheet_id:
                gc.open_by_url(spreadsheet_id) if spreadsheet_id.startswith('http') else gc.open_by_key(spreadsheet_id)
            return True, "Google Sheets connection successful"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Google Sheets connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            gc = self._get_client()
            spreadsheet_id = (self.data_source.api_endpoint or '').strip()
            worksheet_name = (self.data_source.query_template or '').strip() or None
            sh = gc.open_by_url(spreadsheet_id) if spreadsheet_id.startswith('http') else gc.open_by_key(spreadsheet_id)
            ws = sh.worksheet(worksheet_name) if worksheet_name else sh.get_worksheet(0)
            return ws.get_all_records()
        except Exception as e:
            logger.error(f"GoogleSheetsConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            gc = self._get_client()
            spreadsheet_id = (self.data_source.api_endpoint or '').strip()
            sh = gc.open_by_url(spreadsheet_id) if spreadsheet_id.startswith('http') else gc.open_by_key(spreadsheet_id)
            tables = []
            for ws in sh.worksheets():
                headers = ws.row_values(1) if ws.row_count > 0 else []
                columns = [{'name': h, 'type': 'string'} for h in headers if h]
                tables.append({'name': ws.title, 'label': ws.title, 'columns': columns})
            return {'tables': tables, 'filtered_count': 0}
        except Exception as e:
            return {'error': str(e), 'tables': [], 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()


class StripeConnector(BaseDatabaseConnector):
    """
    Connector for Stripe Payments using the stripe library.
    api_key stores the Stripe Secret Key.
    query_template stores the resource type (e.g. 'charges', 'customers', 'invoices').
    """

    def _get_stripe(self):
        try:
            import stripe
        except ImportError:
            raise ImportError("stripe not installed. Run: pip install stripe")

        secret_key = (self.data_source.api_key or '').strip()
        if not secret_key:
            raise ValueError("Stripe connector requires api_key (Stripe Secret Key)")

        stripe.api_key = secret_key
        return stripe

    def test_connection(self) -> Tuple[bool, str]:
        try:
            stripe = self._get_stripe()
            stripe.Balance.retrieve()
            return True, "Stripe connection successful"
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Stripe connection failed: {e}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            stripe = self._get_stripe()
            resource_name = (self.data_source.query_template or 'charges').strip().lower() or 'charges'
            resource_map = {
                'charges': stripe.Charge,
                'customers': stripe.Customer,
                'invoices': stripe.Invoice,
                'subscriptions': stripe.Subscription,
                'paymentintents': stripe.PaymentIntent,
                'payment_intents': stripe.PaymentIntent,
                'products': stripe.Product,
                'prices': stripe.Price,
                'refunds': stripe.Refund,
                'payouts': stripe.Payout,
            }
            resource_class = resource_map.get(resource_name, stripe.Charge)
            items = resource_class.list(limit=100)
            return [item.to_dict() for item in items.auto_paging_iter()]
        except Exception as e:
            logger.error(f"StripeConnector.fetch_data error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        resources = ['charges', 'customers', 'invoices', 'subscriptions',
                     'payment_intents', 'products', 'prices', 'refunds', 'payouts']
        tables = [{'name': r, 'label': r.replace('_', ' ').title(), 'columns': []} for r in resources]
        return {'tables': tables, 'filtered_count': 0}

    def execute_query(self, query: str) -> List[Dict]:
        return self.fetch_data()
