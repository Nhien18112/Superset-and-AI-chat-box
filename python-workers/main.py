from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import json
import logging

import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Superset Automation Worker")

# Superset connection details (Defaults to localhost for local testing outside Docker)
SUPERSET_URL = os.getenv("SUPERSET_URL", "http://localhost:8088")
SUPERSET_USERNAME = os.getenv("SUPERSET_USERNAME", "admin")
SUPERSET_PASSWORD = os.getenv("SUPERSET_PASSWORD", "admin")

class DashboardRequest(BaseModel):
    dataset_id: int
    dashboard_title: str

class SupersetClient:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.csrf_token = None

    def login(self):
        """Authenticate with Superset and retrieve JWT and CSRF tokens."""
        logger.info("Authenticating with Superset...")
        login_url = f"{SUPERSET_URL}/api/v1/security/login"
        payload = {
            "username": SUPERSET_USERNAME,
            "password": SUPERSET_PASSWORD,
            "provider": "db"
        }
        
        try:
            response = self.session.post(login_url, json=payload, timeout=10)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to Superset: {e}")
            raise HTTPException(status_code=500, detail="Cannot connect to Superset")

        if response.status_code != 200:
            logger.error(f"Login failed: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to authenticate with Superset")
            
        self.access_token = response.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        
        # Fetch CSRF token for mutating requests
        csrf_url = f"{SUPERSET_URL}/api/v1/security/csrf_token/"
        csrf_response = self.session.get(csrf_url)
        if csrf_response.status_code != 200:
            logger.error(f"Failed to fetch CSRF token: {csrf_response.text}")
            raise HTTPException(status_code=500, detail="Failed to fetch CSRF token")
            
        self.csrf_token = csrf_response.json().get("result")
        self.session.headers.update({"X-CSRFToken": self.csrf_token})
        logger.info("Authentication successful.")

    def get_or_create_database(self) -> int:
        """Ensure PostgreSQL connection exists in Superset."""
        # Check if exists
        res = self.session.get(f"{SUPERSET_URL}/api/v1/database/")
        dbs = res.json().get("result", [])
        for db in dbs:
            if db["database_name"] == "vdt_db":
                logger.info(f"Database 'vdt_db' already exists with ID: {db['id']}")
                return db["id"]

        logger.info("Creating Database connection for 'vdt_db'...")
        db_payload = {
            "database_name": "vdt_db",
            "sqlalchemy_uri": "postgresql://admin:adminpassword@postgres:5432/vdt_db"
        }
        res = self.session.post(f"{SUPERSET_URL}/api/v1/database/", json=db_payload)
        if res.status_code != 201:
            logger.error(f"Failed to create database: {res.text}")
            raise HTTPException(status_code=500, detail="Failed to connect PostgreSQL to Superset")
        db_id = res.json().get("id")
        logger.info(f"Database connected successfully with ID: {db_id}")
        return db_id

    def get_or_create_dataset(self, db_id: int, table_name: str) -> int:
        """Ensure the Dataset exists in Superset."""
        res = self.session.get(f"{SUPERSET_URL}/api/v1/dataset/")
        datasets = res.json().get("result", [])
        for ds in datasets:
            if ds["table_name"] == table_name:
                logger.info(f"Dataset '{table_name}' already exists with ID: {ds['id']}")
                return ds["id"]

        logger.info(f"Creating Dataset for table '{table_name}'...")
        ds_payload = {
            "database": db_id,
            "table_name": table_name,
            "schema": "public"
        }
        res = self.session.post(f"{SUPERSET_URL}/api/v1/dataset/", json=ds_payload)
        if res.status_code != 201:
            logger.error(f"Failed to create dataset: {res.text}")
            raise HTTPException(status_code=500, detail=f"Failed to create dataset for {table_name}")
        ds_id = res.json().get("id")
        logger.info(f"Dataset created successfully with ID: {ds_id}")
        return ds_id

    def create_chart(self, slice_name: str, dataset_id: int, viz_type: str, params: dict) -> int:
        """Create a chart (slice) in Superset."""
        logger.info(f"Creating chart: {slice_name} ({viz_type})")
        chart_url = f"{SUPERSET_URL}/api/v1/chart/"
        
        payload = {
            "slice_name": slice_name,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": viz_type,
            "params": json.dumps(params)
        }
        
        response = self.session.post(chart_url, json=payload)
        if response.status_code != 201:
            logger.error(f"Failed to create chart {slice_name}: {response.text}")
            raise HTTPException(status_code=500, detail=f"Failed to create chart {slice_name}")
            
        chart_id = response.json().get("id")
        logger.info(f"Chart created successfully with ID: {chart_id}")
        return chart_id

    def create_dashboard(self, dashboard_title: str, charts: list) -> int:
        """Create a dashboard and embed charts using position_json layout."""
        import uuid
        logger.info(f"Creating dashboard: {dashboard_title}")
        dashboard_url = f"{SUPERSET_URL}/api/v1/dashboard/"
        
        position_json = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {
                "type": "ROOT",
                "id": "ROOT_ID",
                "children": ["GRID_ID"]
            },
            "GRID_ID": {
                "type": "GRID",
                "id": "GRID_ID",
                "children": ["ROW_1"],
                "parents": ["ROOT_ID"]
            },
            "ROW_1": {
                "type": "ROW",
                "id": "ROW_1",
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"}
            }
        }
        
        width_per_chart = 4 
        chart_layout_ids = []
        for idx, chart in enumerate(charts):
            cid = chart["id"]
            cname = chart["name"]
            layout_id = f"CHART-{uuid.uuid4().hex[:8]}"
            chart_layout_ids.append(layout_id)
            
            position_json[layout_id] = {
                "type": "CHART",
                "id": layout_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", "ROW_1"],
                "meta": {
                    "width": width_per_chart,
                    "height": 50,
                    "chartId": cid,
                    "sliceName": cname
                }
            }

        position_json["ROW_1"]["children"] = chart_layout_ids

        payload = {
            "dashboard_title": dashboard_title,
            "published": True,
            "position_json": json.dumps(position_json)
        }
        
        response = self.session.post(dashboard_url, json=payload)
        if response.status_code != 201:
            logger.error(f"Failed to create dashboard: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to create dashboard")
            
        dashboard_id = response.json().get("id")
        logger.info(f"Dashboard created successfully with ID: {dashboard_id}")
        return dashboard_id

@app.post("/api/create-dashboard")
def create_dashboard_endpoint(request: DashboardRequest):
    """
    Automates the creation of a Dashboard with 3 predefined charts using Superset REST API.
    """
    client = SupersetClient()
    client.login()

    # 1. Automate Database and Dataset setup
    db_id = client.get_or_create_database()
    
    # We ignore the dataset_id from the request and automatically find/create the 'fact_orders' dataset
    dataset_id = client.get_or_create_dataset(db_id, "fact_orders")
    
    # Common metric definition helper
    def build_metric(col_name: str, aggregate: str, label: str):
        return {
            "expressionType": "SIMPLE",
            "column": {"column_name": col_name},
            "aggregate": aggregate,
            "label": label
        }
    
    # 1. Chart 1: Bar Chart "Total Trading Volume by Ticker"
    chart1_params = {
        "metrics": [build_metric("volume", "SUM", "Total Volume")],
        "groupby": [],
        "x_axis": "ticker_id",
        "row_limit": 100
    }
    chart1_id = client.create_chart(
        slice_name="Total Trading Volume by Ticker",
        dataset_id=dataset_id,
        viz_type="echarts_timeseries_bar",
        params=chart1_params
    )
    
    # 2. Chart 2: Pie Chart "Order Types Distribution"
    chart2_params = {
        "metric": build_metric("order_id", "COUNT", "Count Orders"),
        "groupby": ["order_type"],
        "row_limit": 100
    }
    chart2_id = client.create_chart(
        slice_name="Order Types Distribution",
        dataset_id=dataset_id,
        viz_type="pie",
        params=chart2_params
    )
    
    # 3. Chart 3: Line Chart "Trading Volume over Time"
    chart3_params = {
        "metrics": [build_metric("volume", "SUM", "Total Volume")],
        "groupby": [],
        "x_axis": "order_date",
        "time_grain_sqla": "P1D",
        "row_limit": 100
    }
    chart3_id = client.create_chart(
        slice_name="Trading Volume over Time",
        dataset_id=dataset_id,
        viz_type="echarts_timeseries_line",
        params=chart3_params
    )

    # 4. Create Dashboard
    dashboard_id = client.create_dashboard(
        dashboard_title=request.dashboard_title,
        charts=[
            {"id": chart1_id, "name": "Total Trading Volume by Ticker"},
            {"id": chart2_id, "name": "Order Types Distribution"},
            {"id": chart3_id, "name": "Trading Volume over Time"}
        ]
    )

    # 5. Link Charts to Dashboard (Fixes 'no chart definition associated' error)
    for cid in [chart1_id, chart2_id, chart3_id]:
        res = client.session.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dashboard_id]})
        if res.status_code != 200:
            logger.warning(f"Failed to link chart {cid} to dashboard {dashboard_id}: {res.text}")

    # 6. Enable Embedding and Retrieve UUID
    embed_res = client.session.post(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}/embedded", json={"allowed_domains": []})
    if embed_res.status_code != 200:
        logger.error(f"Failed to enable embedding for dashboard {dashboard_id}: {embed_res.text}")
        raise HTTPException(status_code=500, detail="Failed to enable dashboard embedding")
    
    embedded_uuid = embed_res.json().get("result", {}).get("uuid")

    return {
        "status": "success",
        "dashboard_id": dashboard_id,
        "dashboard_uuid": embedded_uuid,
        "dataset_id": dataset_id,
        "message": f"Dashboard '{request.dashboard_title}' created successfully with 3 charts."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
