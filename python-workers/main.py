from fastapi import FastAPI, HTTPException, Depends, Header
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

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

def require_internal_key(x_internal_api_key: str = Header(...)):
    if not INTERNAL_API_KEY or x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

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
def create_dashboard_endpoint(request: DashboardRequest, _: None = Depends(require_internal_key)):
    """
    Automates the creation of a Dashboard with 3 predefined charts using Superset REST API.
    """
    client = SupersetClient()
    client.login()

    # 1. Automate Database and Dataset setup
    db_id = client.get_or_create_database()
    
    # We ignore the dataset_id from the request and automatically find/create the 'fact_orders' dataset
    dataset_id = client.get_or_create_dataset(db_id, "fact_orders")
    
    def build_metric(col_name: str, aggregate: str, label: str):
        return {
            "expressionType": "SIMPLE",
            "column": {"column_name": col_name},
            "aggregate": aggregate,
            "label": label
        }

    # ── Row 0: KPI cards ──
    kpi1_id = client.create_chart(
        slice_name="Total Orders",
        dataset_id=dataset_id,
        viz_type="big_number_total",
        params={"metric": build_metric("order_id", "COUNT", "Total Orders"), "subheader": "orders recorded"}
    )
    kpi2_id = client.create_chart(
        slice_name="Total Volume Traded",
        dataset_id=dataset_id,
        viz_type="big_number_total",
        params={"metric": build_metric("volume", "SUM", "Total Volume Traded"), "subheader": "shares traded"}
    )
    kpi3_id = client.create_chart(
        slice_name="Active Tickers",
        dataset_id=dataset_id,
        viz_type="big_number_total",
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT ticker_id)", "label": "Active Tickers"},
            "subheader": "distinct tickers"
        }
    )

    # ── Row 1: Main charts ──
    chart1_id = client.create_chart(
        slice_name="Total Trading Volume by Ticker",
        dataset_id=dataset_id,
        viz_type="echarts_timeseries_bar",
        params={"metrics": [build_metric("volume", "SUM", "Total Volume")], "groupby": [], "x_axis": "ticker_id", "row_limit": 100}
    )
    chart2_id = client.create_chart(
        slice_name="Order Types Distribution",
        dataset_id=dataset_id,
        viz_type="pie",
        params={"metric": build_metric("order_id", "COUNT", "Count Orders"), "groupby": ["order_type"], "row_limit": 100}
    )
    chart3_id = client.create_chart(
        slice_name="Trading Volume over Time",
        dataset_id=dataset_id,
        viz_type="echarts_timeseries_line",
        params={"metrics": [build_metric("volume", "SUM", "Total Volume")], "groupby": [], "x_axis": "order_date", "time_grain_sqla": "P1D", "row_limit": 100}
    )

    # ── Build two-row dashboard layout ──
    import uuid

    kpi_charts  = [
        {"id": kpi1_id,    "name": "Total Orders"},
        {"id": kpi2_id,    "name": "Total Volume Traded"},
        {"id": kpi3_id,    "name": "Active Tickers"},
    ]
    main_charts = [
        {"id": chart1_id,  "name": "Total Trading Volume by Ticker"},
        {"id": chart2_id,  "name": "Order Types Distribution"},
        {"id": chart3_id,  "name": "Trading Volume over Time"},
    ]

    position_json = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID":  {"type": "ROOT",  "id": "ROOT_ID",  "children": ["GRID_ID"]},
        "GRID_ID":  {"type": "GRID",  "id": "GRID_ID",  "children": ["ROW_0", "ROW_1"], "parents": ["ROOT_ID"]},
        "ROW_0": {"type": "ROW", "id": "ROW_0", "children": [], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "ROW_1": {"type": "ROW", "id": "ROW_1", "children": [], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
    }

    for kpi in kpi_charts:
        lid = f"CHART-{uuid.uuid4().hex[:8]}"
        position_json[lid] = {
            "type": "CHART", "id": lid, "children": [],
            "parents": ["ROOT_ID", "GRID_ID", "ROW_0"],
            "meta": {"width": 4, "height": 16, "chartId": kpi["id"], "sliceName": kpi["name"]}
        }
        position_json["ROW_0"]["children"].append(lid)

    for chart in main_charts:
        lid = f"CHART-{uuid.uuid4().hex[:8]}"
        position_json[lid] = {
            "type": "CHART", "id": lid, "children": [],
            "parents": ["ROOT_ID", "GRID_ID", "ROW_1"],
            "meta": {"width": 4, "height": 50, "chartId": chart["id"], "sliceName": chart["name"]}
        }
        position_json["ROW_1"]["children"].append(lid)

    dash_res = client.session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json={
        "dashboard_title": request.dashboard_title,
        "published": True,
        "position_json": json.dumps(position_json)
    })
    if dash_res.status_code != 201:
        logger.error(f"Failed to create dashboard: {dash_res.text}")
        raise HTTPException(status_code=500, detail="Failed to create dashboard")
    dashboard_id = dash_res.json().get("id")
    logger.info(f"Dashboard created with ID: {dashboard_id}")

    # Link all charts to the dashboard
    all_chart_ids = [kpi1_id, kpi2_id, kpi3_id, chart1_id, chart2_id, chart3_id]
    for cid in all_chart_ids:
        res = client.session.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dashboard_id]})
        if res.status_code != 200:
            logger.warning(f"Failed to link chart {cid} to dashboard {dashboard_id}: {res.text}")

    # 6. Ensure native Row Level Security (RLS) is created
    # Get Gamma role ID
    role_res = client.session.get(f"{SUPERSET_URL}/api/v1/security/roles/?q={json.dumps({'filters':[{'col':'name','opr':'eq','value':'Gamma'}]})}")
    gamma_role_id = None
    if role_res.status_code == 200:
        roles = role_res.json().get("result", [])
        if roles:
            gamma_role_id = roles[0].get("id")

    if gamma_role_id:
        rls_payload = {
            "name": "Fact Orders Dynamic RLS",
            "description": "Dynamic RLS based on Spring role",
            "filter_type": "Regular",
            "tables": [dataset_id],
            "roles": [gamma_role_id],
            "clause": "{% if current_user_spring_role() == 'ROLE_BROKER' %} investor_id IN (SELECT investor_id FROM dim_investors WHERE broker_id = '{{ current_username() }}') {% elif current_user_spring_role() == 'ROLE_INVESTOR' %} investor_id = '{{ current_username() }}' {% else %} 1=1 {% endif %}"
        }
        
        # Check if RLS exists first to avoid duplicates
        rls_check = client.session.get(f"{SUPERSET_URL}/api/v1/rowlevelsecurity/?q={json.dumps({'filters':[{'col':'name','opr':'eq','value':'Fact Orders Dynamic RLS'}]})}")
        if rls_check.status_code == 200 and len(rls_check.json().get("result", [])) == 0:
            client.session.post(f"{SUPERSET_URL}/api/v1/rowlevelsecurity/", json=rls_payload)
            logger.info("Native RLS rule created for Gamma role.")
        else:
            logger.info("Native RLS rule already exists or check failed.")

        # 7. Grant Gamma role access to the dashboard (required when DASHBOARD_RBAC is True)
        client.session.put(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}", json={"roles": [gamma_role_id]})
        logger.info(f"Dashboard {dashboard_id} granted access to Gamma role.")

    return {
        "status": "success",
        "dashboard_id": dashboard_id,
        "dashboard_uuid": "not_embedded_anymore",
        "dataset_id": dataset_id,
        "message": f"Dashboard '{request.dashboard_title}' created successfully with native RLS."
    }

class ChatRequest(BaseModel):
    query: str
    username: str
    role: str = ""
    history: list = []

@app.post("/api/chat")
def chat_endpoint(request: ChatRequest, _: None = Depends(require_internal_key)):
    """
    Connects to OpenAI API (Codex), binds tools from mcp_superset.py,
    and executes tool calls locally to fetch data or create charts in Superset.
    """
    import os
    import json
    import openai
    from mcp_superset import get_superset_schema, query_dashboard_data, create_custom_chart, get_user_dashboards_and_charts, create_custom_dashboard, get_dashboard_by_name, add_charts_to_existing_dashboard, delete_chart, delete_dashboard, summarize_chart, detect_anomalies, export_chart_csv, change_chart_type
    
    api_key = os.getenv("CODEX_API_KEY")
    base_url = os.getenv("CODEX_BASE_URL")
    
    if not api_key:
        return {"reply": "Error: CODEX_API_KEY is not configured in .env."}
        
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None
    )
    
    system_instruction = (
        f"You are a helpful Data Agent. The current user is '{request.username}'.\n\n"

        "## DECISION: query data vs. create a chart\n"
        "Choose based on the user's intent:\n"
        "  - User wants a NUMBER / VALUE / ANSWER  →  use query_dashboard_data, then state the result in plain text. Do NOT create a chart.\n"
        "  - User explicitly says 'create a chart', 'make a chart', 'plot', 'visualize', 'graph'  →  use create_custom_chart.\n"
        "  - User wants a DASHBOARD  →  create charts first, then create/update the dashboard.\n\n"

        "## Chart and dashboard discovery\n"
        "  - get_user_dashboards_and_charts returns ALL charts the user can see — both their own and\n"
        "    system charts on shared dashboards (e.g. the Automated Market Overview).\n"
        "  - Each chart entry has a 'can_modify' flag:\n"
        "      can_modify=true  → owned by this user: can delete, change type, add to dashboards.\n"
        "      can_modify=false → on a shared/system dashboard (admin-owned): can be summarized,\n"
        "                         analyzed with detect_anomalies, and exported as CSV, but NOT\n"
        "                         deleted or type-changed.\n"
        "  - Always call get_user_dashboards_and_charts first when the user refers to a chart by name.\n"
        "    Match on 'slice_name' (case-insensitive, partial match is fine).\n\n"

        "## WORKFLOW — answering a data question (values / totals / counts)\n"
        "  1. Call get_superset_schema to know the available columns.\n"
        "  2. Call query_dashboard_data with the correct metrics and groupby.\n"
        "  3. Read the returned rows and write a clear, concise answer with the actual numbers.\n"
        "  Do NOT call create_custom_chart for this path.\n\n"

        "## WORKFLOW — adding charts to an EXISTING dashboard\n"
        "  1. Call create_custom_chart for each new chart.\n"
        "  2. Call get_dashboard_by_name with the exact title to get its ID.\n"
        "  3. Call add_charts_to_existing_dashboard with the dashboard ID and new chart IDs.\n"
        "  Never call create_custom_dashboard when the user says 'existing dashboard' or 'add to'.\n\n"

        "## WORKFLOW — creating a BRAND-NEW dashboard\n"
        "  1. Call create_custom_chart for each chart.\n"
        "  2. Call create_custom_dashboard with the new title and all chart IDs.\n\n"

        "## WORKFLOW — explaining / summarizing a chart (data storytelling)\n"
        "  1. If you don't have the chart id, call get_user_dashboards_and_charts to find it by name.\n"
        "  2. Call summarize_chart with the chart id.\n"
        "  3. The returned rows are already filtered to what this user may see. Write a concise analyst "
        "summary: lead with the headline number, then the highest/lowest values, any trend over time, "
        "and any outliers. Always cite the actual numbers; never invent data.\n\n"

        "## WORKFLOW — finding anomalies / outliers in a chart\n"
        "  1. If you don't have the chart id, call get_user_dashboards_and_charts to find it.\n"
        "  2. Call detect_anomalies with the chart id.\n"
        "  3. Report what it found: if anomaly_count is 0 say there are no statistical outliers; "
        "otherwise explain each spike/drop with its value, location, and expected range.\n\n"

        "## WORKFLOW — exporting a chart's data as CSV\n"
        "  1. Find the chart id, then call export_chart_csv.\n"
        "  2. The tool returns a download_url. Give the user a clickable Markdown link "
        "[Download CSV](download_url) and mention it expires in 15 minutes — do not paste the raw rows. "
        "  3. If the tool instead returns inline 'csv' (download storage unavailable), show that in a "
        "fenced ```csv code block.\n\n"

        "## WORKFLOW — changing a chart's visualization type\n"
        "  1. Find the chart id, then call change_chart_type with the new viz_type.\n"
        "  2. If it reports the change was reverted, the chart still has its old type — tell the user "
        "and suggest a type that suits the data. On success emit [OPEN_CHART:<id>].\n\n"

        "## WORKFLOW — deleting a chart or dashboard\n"
        "  1. Call get_user_dashboards_and_charts to look up the id of the chart/dashboard the user means "
        "(match on the name they gave). For a dashboard you may also use get_dashboard_by_name.\n"
        "  2. If exactly one item matches, call delete_chart or delete_dashboard with that id.\n"
        "  3. If several items match the name, list them with their ids and ask the user which one.\n"
        "  4. Users can only delete items they own; relay any permission-denied message plainly.\n\n"

        "## Chart creation rules\n"
        "  - Metrics must be Ad-hoc Metric JSON: "
        "{'expressionType': 'SQL', 'sqlExpression': 'SUM(volume)', 'label': 'Total Volume'} or "
        "{'expressionType': 'SIMPLE', 'column': {'column_name': 'volume'}, 'aggregate': 'SUM', 'label': 'Total Volume'}. "
        "Never pass raw strings for metrics.\n"
        "  - Valid viz_type values: 'echarts_timeseries_line', 'echarts_timeseries_bar', 'pie', 'table', 'big_number_total'. "
        "Never use 'line', 'bar', or 'big_number'.\n"
        "  - For 'echarts_timeseries_bar' and 'echarts_timeseries_line' you MUST set 'x_axis' to the column for the "
        "horizontal axis (e.g. x_axis='order_type' for orders-by-status, x_axis='order_date' for trends over time). "
        "Put the main dimension in 'x_axis', NOT in 'groupby'. Leaving x_axis empty causes a 'Datetime column not "
        "provided' error. Only set 'time_grain_sqla' when x_axis is a date/time column.\n"
        "  - For categorical breakdowns (counts per category) prefer viz_type='pie' or 'table', or "
        "'echarts_timeseries_bar' with x_axis set to that category column.\n"
        "  - Do NOT include 'orderby', 'timeseries_limit_metric', 'series_limit_metric', or 'order_desc' in chart_params.\n"
        "  - create_custom_chart verifies the chart renders before returning. If it returns a "
        "rollback/error message, the chart was NOT created — read the Superset error, fix the "
        "definition (column names, viz_type, x_axis), and call create_custom_chart again. Only claim "
        "success and emit [OPEN_CHART:<id>] when it returns a real chart id.\n"
        "  - After creating a chart include [OPEN_CHART:<id>] in your reply.\n"
        "  - After creating or updating a dashboard include [OPEN_DASHBOARD:<id>].\n\n"

        "## General rules\n"
        "  - Do NOT guess column names — call get_superset_schema first if unsure.\n"
        "  - You do not need to provide user_id to any tools; it is injected automatically.\n"
        "  - Keep answers concise. For data questions, lead with the number, then add context."
    )
    
    # Format messages for OpenAI
    messages = [{"role": "system", "content": system_instruction}]
    for msg in request.history:
        role = "user" if msg.get("isUser") else "assistant"
        messages.append({"role": role, "content": msg.get("text", "")})
        
    messages.append({"role": "user", "content": request.query})
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_superset_schema",
                "description": "Returns the database schema to help you write SQL queries or understand the data structure."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "query_dashboard_data",
                "description": "Fetches data from Superset with RLS applied automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query_params": {"type": "object", "description": "Dictionary containing query details (e.g., metrics, groupby, row_limit)."}
                    },
                    "required": ["query_params"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_custom_chart",
                "description": "Calls Superset API to create a new chart.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_params": {"type": "object", "description": "Dictionary with slice_name, viz_type, metrics, groupby, etc."}
                    },
                    "required": ["chart_params"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_user_dashboards_and_charts",
                "description": "Retrieves metadata about the charts accessible to the user on the database."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_custom_dashboard",
                "description": "Creates a brand-new Superset Dashboard containing the specified chart IDs. Use only when the user explicitly asks to create a NEW dashboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_title": {"type": "string", "description": "The title of the new dashboard."},
                        "chart_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "A list of integer IDs of the charts to include."
                        }
                    },
                    "required": ["dashboard_title", "chart_ids"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_dashboard_by_name",
                "description": "Finds an existing dashboard by its title and returns its ID and the IDs of all charts currently on it. Use this before adding charts to an existing dashboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_title": {"type": "string", "description": "The exact title of the dashboard to find."}
                    },
                    "required": ["dashboard_title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_charts_to_existing_dashboard",
                "description": "Appends new charts to an existing dashboard without removing or changing any current charts. Use this when the user wants to add charts to an existing dashboard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_id": {"type": "integer", "description": "The integer ID of the existing dashboard (get this from get_dashboard_by_name)."},
                        "new_chart_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of chart IDs to append to the dashboard."
                        }
                    },
                    "required": ["dashboard_id", "new_chart_ids"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "summarize_chart",
                "description": "Fetches the data behind an existing chart (with the user's row-level security applied) so you can explain its trends and key findings in natural language. Get the chart id from get_user_dashboards_and_charts first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_id": {"type": "integer", "description": "The integer ID of the chart to summarize."}
                    },
                    "required": ["chart_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "detect_anomalies",
                "description": "Analyzes an existing chart's data (with the user's row-level security applied) and flags statistical outliers — spikes or drops — using the IQR method. Use when the user asks about anomalies, outliers, unusual values, or sudden changes. Get the chart id from get_user_dashboards_and_charts first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_id": {"type": "integer", "description": "The integer ID of the chart to analyze."}
                    },
                    "required": ["chart_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "export_chart_csv",
                "description": "Exports an existing chart's data as raw CSV text (row-level security applied) and returns it inline for the user to copy. Use when the user asks to export, download, or get the raw data of a chart. Get the chart id from get_user_dashboards_and_charts first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_id": {"type": "integer", "description": "The integer ID of the chart to export."}
                    },
                    "required": ["chart_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "change_chart_type",
                "description": "Changes the visualization type of an existing chart the user owns (e.g. switch a bar chart to a pie chart). The chart is re-verified and reverted if the new type fails to render. Get the chart id from get_user_dashboards_and_charts first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_id": {"type": "integer", "description": "The integer ID of the chart to modify."},
                        "new_viz_type": {
                            "type": "string",
                            "description": "The new viz_type.",
                            "enum": ["echarts_timeseries_line", "echarts_timeseries_bar", "pie", "table", "big_number_total"]
                        }
                    },
                    "required": ["chart_id", "new_viz_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_chart",
                "description": "Deletes a chart the user owns. Get the chart id from get_user_dashboards_and_charts first. Only the owner can delete it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_id": {"type": "integer", "description": "The integer ID of the chart to delete."}
                    },
                    "required": ["chart_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_dashboard",
                "description": "Deletes a dashboard the user owns (charts on it are kept). Get the dashboard id from get_user_dashboards_and_charts or get_dashboard_by_name first. Only the owner can delete it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_id": {"type": "integer", "description": "The integer ID of the dashboard to delete."}
                    },
                    "required": ["dashboard_id"]
                }
            }
        }
    ]
    
    try:
        def call_openai(msgs, max_retries=3):
            import time
            for attempt in range(max_retries):
                try:
                    return client.chat.completions.create(
                        model=os.getenv("CODEX_MODEL", "gpt-5.4"),
                        messages=msgs,
                        tools=tools,
                        temperature=0.1
                    )
                except Exception as e:
                    if '503' in str(e) and attempt < max_retries - 1:
                        logger.warning(f"503 received, retrying in {2 ** attempt} seconds...")
                        time.sleep(2 ** attempt)
                    else:
                        raise e
                        
        response = call_openai(messages)
        message = response.choices[0].message
        
        # Handle tool calls
        while message.tool_calls:
            # We append the model's message to context
            messages.append(message)
            
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                
                try:
                    if name == "get_superset_schema":
                        result = get_superset_schema()
                    elif name == "query_dashboard_data":
                        args["user_id"] = request.username
                        args["user_role"] = request.role
                        result = query_dashboard_data(**args)
                    elif name == "create_custom_chart":
                        args["user_id"] = request.username
                        result = create_custom_chart(**args)
                    elif name == "get_user_dashboards_and_charts":
                        args["user_id"] = request.username
                        result = get_user_dashboards_and_charts(**args)
                    elif name == "create_custom_dashboard":
                        args["user_id"] = request.username
                        result = create_custom_dashboard(**args)
                    elif name == "get_dashboard_by_name":
                        result = get_dashboard_by_name(**args)
                    elif name == "add_charts_to_existing_dashboard":
                        result = add_charts_to_existing_dashboard(**args)
                    elif name == "summarize_chart":
                        args["user_id"] = request.username
                        args["user_role"] = request.role
                        result = summarize_chart(**args)
                    elif name == "detect_anomalies":
                        args["user_id"] = request.username
                        args["user_role"] = request.role
                        result = detect_anomalies(**args)
                    elif name == "export_chart_csv":
                        args["user_id"] = request.username
                        args["user_role"] = request.role
                        result = export_chart_csv(**args)
                    elif name == "change_chart_type":
                        args["user_id"] = request.username
                        result = change_chart_type(**args)
                    elif name == "delete_chart":
                        args["user_id"] = request.username
                        result = delete_chart(**args)
                    elif name == "delete_dashboard":
                        args["user_id"] = request.username
                        result = delete_dashboard(**args)
                    else:
                        result = f"Unknown tool {name}"
                except Exception as e:
                    result = f"Error executing {name}: {str(e)}"
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": str(result)
                })
            
            response = call_openai(messages)
            message = response.choices[0].message
            
        final_content = message.content
        return {"reply": final_content if final_content is not None else "I have completed the task."}
        
    except Exception as e:
        logger.error(f"OpenAI Chat Error: {e}")
        return {"reply": f"Error executing Data Agent: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
