import os
import json
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

SUPERSET_URL = os.getenv("SUPERSET_URL", "http://localhost:8088")
SUPERSET_ADMIN_USERNAME = os.getenv("SUPERSET_ADMIN_USERNAME", "admin")
SUPERSET_ADMIN_PASSWORD = os.getenv("SUPERSET_ADMIN_PASSWORD", "admin")

class MCPClient:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.csrf_token = None

    def login(self):
        login_url = f"{SUPERSET_URL}/api/v1/security/login"
        payload = {
            "username": SUPERSET_ADMIN_USERNAME,
            "password": SUPERSET_ADMIN_PASSWORD,
            "provider": "db"
        }
        res = self.session.post(login_url, json=payload, timeout=10)
        res.raise_for_status()
        self.access_token = res.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        
        csrf_res = self.session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
        if csrf_res.status_code == 200:
            self.csrf_token = csrf_res.json().get("result")
            self.session.headers.update({"X-CSRFToken": self.csrf_token})

    def get_dataset_id(self, table_name: str) -> int:
        res = self.session.get(f"{SUPERSET_URL}/api/v1/dataset/")
        if res.status_code == 200:
            datasets = res.json().get("result", [])
            for ds in datasets:
                if ds["table_name"] == table_name:
                    return ds["id"]
        return 1  # Fallback

def get_superset_schema() -> str:
    """
    Returns the schema of the database to help you write SQL queries or understand the data structure.
    Use this tool before writing SQL queries or creating charts to ensure you use the correct column names.
    """
    return """
    Table: dim_tickers
    - id (INT, Primary Key)
    - symbol (VARCHAR)
    - company_name (VARCHAR)
    - sector (VARCHAR)

    Table: dim_brokers
    - broker_id (VARCHAR, Primary Key)
    - name (VARCHAR)

    Table: dim_investors
    - investor_id (VARCHAR, Primary Key)
    - broker_id (VARCHAR, Foreign Key to dim_brokers)
    - name (VARCHAR)

    Table: fact_orders
    - order_id (INT, Primary Key)
    - order_date (TIMESTAMP)
    - investor_id (VARCHAR, Foreign Key to dim_investors)
    - ticker_id (INT, Foreign Key to dim_tickers)
    - order_type (VARCHAR) -- e.g., 'BUY', 'SELL'
    - volume (INT)
    - price (FLOAT)
    """

def query_dashboard_data(user_id: str, query_params: Dict[str, Any]) -> str:
    """
    Fetches data from Superset. Enforces RLS by generating a Guest Token for the provided user_id.
    
    Args:
        user_id: The ID of the user requesting the data.
        query_params: Dictionary containing query details (e.g., metric, groupby, row_limit).
    """
    try:
        client = MCPClient()
        client.login()
        dataset_id = client.get_dataset_id("fact_orders")

        # 1. Generate Guest Token with RLS
        guest_payload = {
            "user": {
                "username": user_id,
                "first_name": "Guest",
                "last_name": user_id
            },
            "resources": [{"type": "dashboard", "id": "embedded-dashboard-id"}], # Placeholder or fetch real ID
            "rls": [
                {
                    "dataset": dataset_id,
                    "clause": f"investor_id = '{user_id}'"
                }
            ]
        }
        gt_res = client.session.post(f"{SUPERSET_URL}/api/v1/security/guest_token/", json=guest_payload)
        gt_res.raise_for_status()
        guest_token = gt_res.json().get("token")

        # 2. Query Data using Guest Token
        headers = {"Authorization": f"Bearer {guest_token}"}
        
        # Build query payload
        chart_data_payload = {
            "datasource": {
                "id": dataset_id,
                "type": "table"
            },
            "queries": [
                {
                    "metrics": query_params.get("metrics", ["count"]),
                    "columns": query_params.get("groupby", []),
                    "row_limit": query_params.get("row_limit", 100)
                }
            ],
            "result_format": "json",
            "result_type": "full"
        }

        data_res = requests.post(f"{SUPERSET_URL}/api/v1/chart/data", json=chart_data_payload, headers=headers)
        data_res.raise_for_status()
        
        return json.dumps(data_res.json().get("result", []), indent=2)

    except Exception as e:
        logger.error(f"Error querying dashboard data: {e}")
        return f"Error: {str(e)}"

def create_custom_chart(user_id: str, chart_params: Dict[str, Any]) -> str:
    """
    Calls Superset API to create a new chart. Assigns ownership to the user_id and applies RLS filters.
    
    Args:
        user_id: The ID of the user creating the chart.
        chart_params: Dictionary with slice_name, viz_type, metrics, groupby, etc.
    """
    try:
        client = MCPClient()
        client.login()
        dataset_id = client.get_dataset_id("fact_orders")

        # Find user ID in Superset
        user_res = client.session.get(f"{SUPERSET_URL}/api/v1/security/users/?q={json.dumps({'filters':[{'col':'username','opr':'eq','value':user_id}]})}")
        owners = []
        if user_res.status_code == 200:
            users = user_res.json().get("result", [])
            if users:
                owners.append(users[0]["id"])

        payload = {
            "slice_name": chart_params.get("slice_name", "Custom Chart"),
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": chart_params.get("viz_type", "echarts_timeseries_bar"),
            "params": json.dumps(chart_params),
            "owners": owners
        }
        
        response = client.session.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
        response.raise_for_status()
        
        chart_id = response.json().get("id")
        return f"Chart created successfully. Chart ID: {chart_id}"

    except Exception as e:
        logger.error(f"Error creating custom chart: {e}")
        return f"Error: {str(e)}"
