import os
import json
import logging
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Using the existing SupersetClient from main.py
# We can import it if it's refactored, or just duplicate the minimal needed logic.
# For simplicity and encapsulation of the MCP server, we'll keep it self-contained or import.
try:
    from main import SupersetClient
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Initialize FastMCP Server
mcp = FastMCP("VDT_Superset_Agent")

@mcp.tool()
def get_database_schema() -> str:
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

@mcp.tool()
def create_superset_chart(
    slice_name: str = Field(..., description="The title of the chart"),
    viz_type: str = Field(..., description="The type of chart (e.g., 'echarts_timeseries_bar', 'pie', 'echarts_timeseries_line')"),
    metrics: list[dict] = Field(..., description="List of metric dictionaries, e.g., [{'expressionType': 'SIMPLE', 'column': {'column_name': 'volume'}, 'aggregate': 'SUM', 'label': 'Total Volume'}]"),
    groupby: list[str] = Field(..., description="List of columns to group by"),
    x_axis: str = Field(None, description="The column to use for the X-axis (required for timeseries charts)"),
    time_grain_sqla: str = Field(None, description="Time granularity (e.g., 'P1D' for daily)"),
    username: str = Field(..., description="The username of the user requesting the chart. This is required to set the ownership.")
) -> str:
    """
    Creates a new chart in Superset and assigns ownership to the requesting user.
    The chart is automatically bound to the 'fact_orders' dataset which enforces Row Level Security (RLS).
    """
    try:
        client = SupersetClient()
        client.login()

        # Find db and dataset
        db_id = client.get_or_create_database()
        dataset_id = client.get_or_create_dataset(db_id, "fact_orders")

        # Build params
        params = {
            "metrics": metrics,
            "groupby": groupby,
            "row_limit": 100
        }
        if x_axis:
            params["x_axis"] = x_axis
        if time_grain_sqla:
            params["time_grain_sqla"] = time_grain_sqla

        if viz_type == "pie" and metrics:
            params["metric"] = metrics[0]
            del params["metrics"]

        # Find user ID in Superset
        user_res = client.session.get(f"{os.getenv('SUPERSET_URL', 'http://localhost:8088')}/api/v1/security/users/?q={json.dumps({'filters':[{'col':'username','opr':'eq','value':username}]})}")
        owners = []
        if user_res.status_code == 200:
            users = user_res.json().get("result", [])
            if users:
                owners.append(users[0]["id"])

        chart_url = f"{os.getenv('SUPERSET_URL', 'http://localhost:8088')}/api/v1/chart/"
        payload = {
            "slice_name": slice_name,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": viz_type,
            "params": json.dumps(params),
            "owners": owners
        }
        
        response = client.session.post(chart_url, json=payload)
        if response.status_code != 201:
            return f"Failed to create chart: {response.text}"
            
        chart_id = response.json().get("id")
        dashboard_url = f"{os.getenv('SUPERSET_URL', 'http://localhost:8088')}/superset/explore/?form_data=%7B%22slice_id%22%3A%20{chart_id}%7D"
        
        return f"Successfully created chart '{slice_name}' (ID: {chart_id}). It is now available in your Superset workspace."
    except Exception as e:
        logger.error(f"Error in create_superset_chart: {e}")
        return f"Error creating chart: {str(e)}"

if __name__ == "__main__":
    mcp.run()
