import os
import re
import json
import logging
import requests
import time
from typing import Dict, Any

# ── SQL expression security ──────────────────────────────────────────────────
# Only AGGREGATE([DISTINCT] column) patterns are allowed in SQL metric
# expressions. Everything else — subqueries, DDL, semicolons, system tables —
# is rejected before it reaches the database.

_SAFE_AGG_RE = re.compile(
    r'^\s*(SUM|COUNT|AVG|MAX|MIN)\s*\(\s*(DISTINCT\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*$',
    re.IGNORECASE,
)

_ALLOWED_AGGREGATES = {"SUM", "COUNT", "AVG", "MAX", "MIN"}

_BLOCKED_KEYWORDS = frozenset([
    "drop", "delete", "insert", "update", "truncate", "create", "alter",
    "exec", "execute", "call", "union", "sleep", "benchmark",
    "load_file", "outfile", "dumpfile", "pg_read_file", "pg_ls_dir",
    "information_schema", "pg_catalog", "pg_shadow", "pg_user",
])


def _validate_sql_expression(sql_expr: str, valid_columns: set) -> tuple:
    """
    Returns (is_safe: bool, error_msg: str).
    Accepts only AGGREGATE([DISTINCT] column) — rejects everything else.
    """
    stripped = sql_expr.strip()

    # Structural injection characters
    for bad in (";", "--", "/*", "*/", "\n", "\r"):
        if bad in stripped:
            return False, f"Illegal character sequence '{bad}' in SQL expression."

    # Dangerous keyword blocklist
    lower = stripped.lower()
    for kw in _BLOCKED_KEYWORDS:
        if kw in lower:
            return False, f"Blocked keyword '{kw}' in SQL expression."

    # Must be exactly AGGREGATE([DISTINCT] column)
    m = _SAFE_AGG_RE.fullmatch(stripped)
    if not m:
        return False, (
            f"SQL expression '{stripped}' is not permitted. "
            "Only AGGREGATE([DISTINCT] column) patterns are allowed, "
            "e.g. SUM(volume), COUNT(DISTINCT investor_id)."
        )

    col = m.group(3)
    if valid_columns and col not in valid_columns:
        return False, (
            f"Column '{col}' does not exist in fact_orders. "
            f"Valid columns: {sorted(valid_columns)}"
        )

    return True, ""


def _safe_identifier(name: str) -> str:
    """Raise if a column/identifier name contains anything other than word chars."""
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Unsafe identifier: '{name}'")
    return name

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
        raise RuntimeError(f"Dataset '{table_name}' not found in Superset. Make sure the dashboard has been initialized first.")

_schema_cache: Dict[str, Any] = {
    "columns_by_table": None,
    "temporal_by_table": None,
    "schema_string": None,
    "fetched_at": 0.0,
}
_SCHEMA_TTL = 300  # seconds — refresh every 5 minutes

_TEMPORAL_TYPE_RE = re.compile(r"DATE|TIME|TIMESTAMP", re.IGNORECASE)


def _load_schema_cache() -> None:
    """Login as admin, walk all registered Superset datasets, and populate the in-memory cache."""
    client = MCPClient()
    client.login()

    res = client.session.get(f"{SUPERSET_URL}/api/v1/dataset/")
    res.raise_for_status()
    datasets = res.json().get("result", [])

    columns_by_table: Dict[str, list] = {}
    temporal_by_table: Dict[str, set] = {}
    lines: list[str] = []

    for ds in datasets:
        table_name = ds["table_name"]
        ds_id = ds["id"]
        detail_res = client.session.get(f"{SUPERSET_URL}/api/v1/dataset/{ds_id}")
        if detail_res.status_code != 200:
            continue
        cols = detail_res.json().get("result", {}).get("columns", [])
        col_names = [c["column_name"] for c in cols]
        columns_by_table[table_name] = col_names
        temporal_by_table[table_name] = {
            c["column_name"] for c in cols
            if c.get("is_dttm") or _TEMPORAL_TYPE_RE.search(str(c.get("type", "")))
        }
        lines.append(f"Table: {table_name}")
        for c in cols:
            lines.append(f"  - {c['column_name']} ({c.get('type', 'UNKNOWN')})")
        lines.append("")

    _schema_cache["columns_by_table"] = columns_by_table
    _schema_cache["temporal_by_table"] = temporal_by_table
    _schema_cache["schema_string"] = "\n".join(lines)
    _schema_cache["fetched_at"] = time.time()
    logger.info("Schema cache refreshed: %d table(s) loaded.", len(columns_by_table))


def _get_schema() -> tuple:
    """Return (columns_by_table, schema_string), refreshing the cache when stale."""
    if time.time() - _schema_cache["fetched_at"] > _SCHEMA_TTL or _schema_cache["schema_string"] is None:
        try:
            _load_schema_cache()
        except Exception as e:
            logger.warning("Could not refresh schema cache: %s", e)
            if _schema_cache["schema_string"] is None:
                return {}, ""
    return _schema_cache["columns_by_table"], _schema_cache["schema_string"]


def get_superset_schema() -> str:
    """Returns the live database schema fetched from Superset (cached for 5 minutes)."""
    _, schema_string = _get_schema()
    return schema_string or "Schema temporarily unavailable — please retry."


def _validate_columns(params: Dict[str, Any], table: str = "fact_orders") -> list[str]:
    """
    Pre-flight check: validate column references in AI-generated params against the live schema.
    Returns a list of error strings; an empty list means all columns are valid.
    """
    columns_by_table, _ = _get_schema()
    if not columns_by_table or table not in columns_by_table:
        return []  # cannot validate without a live schema — let Superset surface the error

    valid = set(columns_by_table[table])
    errors: list[str] = []

    for col in params.get("groupby", []):
        if isinstance(col, str) and col not in valid:
            errors.append(f"Column '{col}' does not exist in '{table}'.")

    x_axis = params.get("x_axis")
    if isinstance(x_axis, str) and x_axis not in valid:
        errors.append(f"x_axis column '{x_axis}' does not exist in '{table}'.")

    all_metrics = list(params.get("metrics", []))
    single = params.get("metric")
    if isinstance(single, dict):
        all_metrics.insert(0, single)

    for m in all_metrics:
        if isinstance(m, dict) and m.get("expressionType") == "SIMPLE":
            col = (m.get("column") or {}).get("column_name")
            if col and col not in valid:
                errors.append(f"Metric column '{col}' does not exist in '{table}'.")

    if errors:
        errors.append(f"Valid columns for '{table}': {sorted(valid)}")
    return errors

def _metric_to_sql(metric: Any, valid_columns=None) -> tuple:
    """
    Convert an AI-generated metric object to (sql_expression, label).
    Raises ValueError if the expression fails security validation.
    """
    if isinstance(metric, str):
        return "COUNT(*)", metric

    expr_type = metric.get("expressionType", "")
    label = metric.get("label", "value")

    if expr_type == "SQL":
        sql_expr = metric.get("sqlExpression", "COUNT(*)")
        ok, err = _validate_sql_expression(sql_expr, valid_columns or set())
        if not ok:
            raise ValueError(f"Rejected metric SQL expression — {err}")
        return sql_expr, label

    if expr_type == "SIMPLE":
        col = _safe_identifier((metric.get("column") or {}).get("column_name", "order_id"))
        agg = metric.get("aggregate", "COUNT").upper()
        if agg not in _ALLOWED_AGGREGATES:
            raise ValueError(
                f"Aggregate function '{agg}' is not allowed. "
                f"Permitted: {_ALLOWED_AGGREGATES}"
            )
        return f"{agg}({col})", label

    return "COUNT(*)", label


def query_dashboard_data(user_id: str, query_params: Dict[str, Any], user_role: str = "") -> str:
    """
    Queries fact_orders directly from PostgreSQL with role-aware RLS filters.
    - ROLE_INVESTOR: filters to that investor's own rows only.
    - ROLE_BROKER: filters to all investors assigned to that broker.
    """
    import re
    import psycopg2
    import psycopg2.extras

    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        return "Error: Invalid user identifier."

    validation_errors = _validate_columns(query_params)
    if validation_errors:
        return "Pre-flight validation failed — correct these column errors and retry: " + "; ".join(validation_errors)

    try:
        db_url = os.getenv("POSTGRES_URL", "postgresql://admin:adminpassword@postgres:5432/vdt_db")
        # Parse the DSN for psycopg2
        import re as _re
        m = _re.match(r'postgresql://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)', db_url)
        if not m:
            return "Error: Invalid POSTGRES_URL format."
        pg_user, pg_pass, pg_host, pg_port, pg_db = m.groups()

        conn = psycopg2.connect(
            host=pg_host, port=int(pg_port), dbname=pg_db,
            user=pg_user, password=pg_pass
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch valid columns for SQL expression validation
        columns_by_table, _ = _get_schema()
        valid_cols = set(columns_by_table.get("fact_orders", []))

        # Build SELECT clause from AI-generated metrics
        metrics = query_params.get("metrics", [{"expressionType": "SIMPLE",
                                                 "column": {"column_name": "order_id"},
                                                 "aggregate": "COUNT", "label": "Total Orders"}])
        groupby = query_params.get("groupby", [])
        row_limit = min(int(query_params.get("row_limit", 100)), 1000)

        select_parts = []
        for m_obj in metrics:
            expr, lbl = _metric_to_sql(m_obj, valid_cols)
            safe_lbl = re.sub(r'[^\w\s\-]', '', lbl)[:64]
            select_parts.append(f'{expr} AS "{safe_lbl}"')

        # _safe_identifier raises ValueError on any non-word characters
        group_cols = [f'"{_safe_identifier(c)}"' for c in groupby]
        if group_cols:
            select_parts = group_cols + select_parts

        select_clause = ", ".join(select_parts)
        group_clause = f"GROUP BY {', '.join(group_cols)}" if group_cols else ""

        # RLS: build WHERE clause
        params: list = []
        if user_role == "ROLE_BROKER":
            where_clause = "investor_id IN (SELECT investor_id FROM dim_investors WHERE broker_id = %s)"
            params.append(user_id)
        else:
            where_clause = "investor_id = %s"
            params.append(user_id)

        sql = f"""
            SELECT {select_clause}
            FROM fact_orders
            WHERE {where_clause}
            {group_clause}
            LIMIT {row_limit}
        """

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return "Query returned no results for your account."

        return json.dumps([dict(r) for r in rows], indent=2, default=str)

    except Exception as e:
        logger.error(f"Error querying dashboard data: {e}")
        return f"Error: {str(e)}"

_TIMESERIES_VIZ = {
    "echarts_timeseries_bar",
    "echarts_timeseries_line",
    "echarts_timeseries_area",
    "echarts_timeseries_scatter",
    "echarts_timeseries",
}


def _normalize_chart_params(chart_params: Dict[str, Any], table: str = "fact_orders") -> None:
    """
    Repair AI-generated chart params in place so they render in Superset.

    The time-series viz types (echarts_timeseries_*) require an `x_axis`. When the
    model leaves x_axis empty and puts the dimension in `groupby`, Superset falls
    back to the dataset's main datetime column — which fact_orders does not have —
    and raises "Datetime column not provided". We fix that by:
      - promoting the first groupby column to x_axis when x_axis is missing, else
        falling back to a temporal column if one exists;
      - dropping time_grain_sqla when the resolved x_axis is not a temporal column
        (a time grain on a categorical axis re-triggers the same datetime error).
    """
    viz = chart_params.get("viz_type", "")

    # ── Metric field shape ──
    # pie / big_number_total read a singular `metric`; bar / line / table read a
    # `metrics` list. A mismatch makes the frontend viz crash on render with
    # "Cannot read properties of undefined (reading 'label')".
    metrics = list(chart_params.get("metrics") or [])
    single = chart_params.get("metric")
    if single and single not in metrics:
        metrics = [single] + metrics
    if not metrics:
        metrics = [{"expressionType": "SIMPLE", "column": {"column_name": "order_id"},
                    "aggregate": "COUNT", "label": "count"}]
    if viz in ("pie", "big_number_total"):
        chart_params["metric"] = metrics[0]
        chart_params.pop("metrics", None)
    else:
        chart_params["metrics"] = metrics
        chart_params.pop("metric", None)

    # ── Time-series x-axis handling ──
    if viz not in _TIMESERIES_VIZ:
        return

    _, schema_string = _get_schema()  # ensures cache is warm
    temporal = (_schema_cache.get("temporal_by_table") or {}).get(table, set())

    x_axis = chart_params.get("x_axis")
    groupby = chart_params.get("groupby") or []

    if not x_axis:
        if groupby:
            x_axis = groupby[0]
            chart_params["groupby"] = groupby[1:]
        elif temporal:
            x_axis = sorted(temporal)[0]
        chart_params["x_axis"] = x_axis

    # A non-temporal x_axis must not carry a time grain, or Superset still demands
    # a datetime column.
    if x_axis and x_axis not in temporal:
        chart_params.pop("time_grain_sqla", None)
        chart_params.pop("granularity_sqla", None)


def _build_query_context(dataset_id: int, chart_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a Superset query_context from chart params.

    Charts created through the REST API only carry `params` (form_data). The
    dashboard render path and the chart-data endpoint both need a saved
    `query_context`; without it, echarts_timeseries_* charts fall back to legacy
    time-series handling and fail with "Datetime column not provided". Saving this
    context makes every chart render reliably and lets us verify it after creation.
    """
    viz = chart_params.get("viz_type", "")

    metrics = list(chart_params.get("metrics") or [])
    single = chart_params.get("metric")
    if single and single not in metrics:
        metrics = [single] + metrics
    if not metrics:
        metrics = [{"expressionType": "SIMPLE", "column": {"column_name": "order_id"},
                    "aggregate": "COUNT", "label": "count"}]

    groupby = [c for c in (chart_params.get("groupby") or []) if c]
    x_axis = chart_params.get("x_axis")

    if viz == "big_number_total":
        columns: list = []
    elif viz in _TIMESERIES_VIZ:
        columns = ([x_axis] if x_axis else []) + groupby
    else:  # pie, table, and friends
        columns = groupby

    query = {
        "metrics": metrics,
        "columns": columns,
        "orderby": [],
        "row_limit": int(chart_params.get("row_limit", 1000) or 1000),
        "annotation_layers": [],
        "filters": [],
        "extras": {},
    }
    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": [query],
        "form_data": chart_params,
        "result_format": "json",
        "result_type": "full",
    }


def _verify_chart(client, chart_id: int) -> tuple:
    """
    Execute a freshly-created chart against its saved query_context.
    Returns (ok: bool, error_msg: str). Only a genuine query failure makes
    ok False — transport hiccups in the verifier do not block chart creation.
    """
    try:
        res = client.session.get(
            f"{SUPERSET_URL}/api/v1/chart/{chart_id}/data/?format=json&type=results"
        )
    except Exception as e:
        logger.warning("Chart %s verification could not run: %s", chart_id, e)
        return True, ""

    if res.status_code != 200:
        try:
            msg = res.json().get("message") or res.text[:300]
        except Exception:
            msg = res.text[:300]
        return False, f"HTTP {res.status_code}: {msg}"

    try:
        result = res.json().get("result")
        if isinstance(result, list) and result:
            if result[0].get("error"):
                return False, str(result[0]["error"])
            if result[0].get("status") == "failed":
                return False, "Query failed."
    except Exception:
        pass
    return True, ""


def _get_chart_rows(user_id: str, chart_id: int, user_role: str = ""):
    """
    Shared RLS-safe data fetch for the analyst tools (summarize / anomalies / export).

    Looks up a chart, reconstructs its query from the stored params, and runs it
    THROUGH query_dashboard_data so row-level security is applied — the caller never
    sees rows the user isn't entitled to.

    Returns (meta, rows, error):
      - meta:  dict with chart_id, slice_name, viz_type, groupby  (None only when the
               chart itself could not be fetched)
      - rows:  list[dict] of result rows, or None
      - error: a message string when there are no rows / the query failed, else None
    """
    client = MCPClient()
    client.login()

    res = client.session.get(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
    if res.status_code == 404:
        return None, None, f"No chart with ID {chart_id} exists."
    if res.status_code != 200:
        return None, None, f"Error fetching chart {chart_id}: HTTP {res.status_code}"

    chart = res.json().get("result", {})
    params_str = chart.get("params", "{}")
    try:
        params = json.loads(params_str) if isinstance(params_str, str) else (params_str or {})
    except Exception:
        params = {}

    metrics = list(params.get("metrics") or [])
    single = params.get("metric")
    if single and single not in metrics:
        metrics = [single] + metrics

    groupby = [c for c in (params.get("groupby") or []) if c]
    x_axis = params.get("x_axis")
    if x_axis and x_axis not in groupby:
        groupby = [x_axis] + groupby

    query_params = {"metrics": metrics, "groupby": groupby, "row_limit": params.get("row_limit", 200)}

    meta = {
        "chart_id": chart_id,
        "slice_name": chart.get("slice_name"),
        "viz_type": chart.get("viz_type"),
        "groupby": groupby,
    }

    data = query_dashboard_data(user_id, query_params, user_role)
    try:
        rows = json.loads(data)
    except Exception:
        return meta, None, data  # "no results" / "Error: ..." message string
    if not isinstance(rows, list):
        return meta, None, str(rows)
    return meta, rows, None


def _resolve_superset_user_id(client, username: str):
    """Return Superset's internal numeric user id for a username, or None."""
    res = client.session.get(
        f"{SUPERSET_URL}/api/v1/security/users/?q="
        + json.dumps({"filters": [{"col": "username", "opr": "eq", "value": username}]})
    )
    if res.status_code == 200:
        users = res.json().get("result", [])
        if users:
            return users[0]["id"]
    return None


def _grant_gamma_datasource_access(dataset_id: int) -> None:
    """
    Ensure the Gamma role holds datasource_access on the given dataset.

    Without it, adding a Gamma user as a chart owner — or later editing a
    Gamma-owned chart — fails with
    "FORBIDDEN ... requires the datasource N, database or all_datasource_access".

    This is done against the metadata DB because FAB's REST RoleApi cannot edit a
    role's permissions (its edit_columns is just `name`). FAB reads role permissions
    from the DB per request, so the grant takes effect without a restart. Idempotent
    via the (permission_view_id, role_id) unique constraint.
    """
    import re as _re
    import psycopg2
    try:
        db_url = os.getenv("POSTGRES_URL", "postgresql://admin:adminpassword@postgres:5432/vdt_db")
        m = _re.match(r'postgresql://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)', db_url)
        if not m:
            return
        pg_user, pg_pass, pg_host, pg_port, pg_db = m.groups()
        conn = psycopg2.connect(host=pg_host, port=int(pg_port), dbname=pg_db,
                                user=pg_user, password=pg_pass)
        try:
            cur = conn.cursor()
            # Match the datasource_access perm whose view-menu ends in (id:<dataset_id>),
            # which uniquely identifies this dataset's datasource permission.
            cur.execute(
                """
                INSERT INTO ab_permission_view_role (id, permission_view_id, role_id)
                SELECT (SELECT COALESCE(MAX(id), 0) + 1 FROM ab_permission_view_role),
                       pv.id, r.id
                FROM ab_permission_view pv
                JOIN ab_permission p ON p.id = pv.permission_id
                JOIN ab_view_menu vm ON vm.id = pv.view_menu_id
                JOIN ab_role r ON r.name = 'Gamma'
                WHERE p.name = 'datasource_access'
                  AND vm.name LIKE %s
                ON CONFLICT (permission_view_id, role_id) DO NOTHING
                """,
                (f"%(id:{dataset_id})",),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Could not grant Gamma datasource access: %s", e)


def create_custom_chart(user_id: str, chart_params: Dict[str, Any]) -> str:
    """
    Calls Superset API to create a new chart. Assigns ownership to the user_id and applies RLS filters.

    Args:
        user_id: The ID of the user creating the chart.
        chart_params: Dictionary with slice_name, viz_type, metrics, groupby, etc.
    """
    validation_errors = _validate_columns(chart_params)
    if validation_errors:
        return "Pre-flight validation failed — correct these column errors and retry: " + "; ".join(validation_errors)

    _normalize_chart_params(chart_params)

    try:
        client = MCPClient()
        client.login()
        dataset_id = client.get_dataset_id("fact_orders")
        _grant_gamma_datasource_access(dataset_id)

        # Find user ID in Superset
        user_res = client.session.get(f"{SUPERSET_URL}/api/v1/security/users/?q={json.dumps({'filters':[{'col':'username','opr':'eq','value':user_id}]})}")
        owners = []
        if user_res.status_code == 200:
            users = user_res.json().get("result", [])
            if users:
                owners.append(users[0]["id"])

        # Strip fields that cause "Found invalid orderby options" when set via API
        # without matching metric definitions registered on the dataset
        for bad_key in ("orderby", "timeseries_limit_metric", "series_limit_metric",
                        "order_desc", "legacy_order_by"):
            chart_params.pop(bad_key, None)

        # Do NOT include owners in the initial POST — Superset 4.x will validate
        # datasource access for every listed owner, and Gamma-role users fail that
        # check, causing a 403 even when the requesting user is admin.
        payload = {
            "slice_name": chart_params.get("slice_name", "Custom Chart"),
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": chart_params.get("viz_type", "echarts_timeseries_bar"),
            "params": json.dumps(chart_params),
        }

        response = client.session.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
        if response.status_code not in (200, 201):
            try:
                detail = response.json().get("message") or response.json().get("errors") or response.text
            except Exception:
                detail = response.text
            return f"Error creating chart: HTTP {response.status_code}: {detail}"

        chart_id = response.json().get("id")

        # Save a query_context so the chart renders in dashboards (echarts_timeseries_*
        # charts otherwise fail with "Datetime column not provided") and so it can be
        # verified below.
        qc = _build_query_context(dataset_id, chart_params)
        qc_res = client.session.put(
            f"{SUPERSET_URL}/api/v1/chart/{chart_id}",
            json={"query_context": json.dumps(qc), "query_context_generation": True},
        )
        if qc_res.status_code not in (200, 201):
            client.session.delete(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
            return (
                f"Error saving chart query context (HTTP {qc_res.status_code}). "
                "Chart was rolled back; please retry."
            )

        # Verify the chart actually executes before reporting success. If it errors,
        # roll back and hand the Superset error to the model so it can correct the
        # definition (wrong column, viz_type, x_axis, etc.) and retry.
        ok, verr = _verify_chart(client, chart_id)
        if not ok:
            client.session.delete(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
            return (
                f"Chart was rejected because it failed to render and has been rolled back. "
                f"Superset error: {verr}. Fix the chart definition (check column names against "
                "the schema, the viz_type, and x_axis) and try create_custom_chart again."
            )

        # Add user as owner in a follow-up PUT so datasource access of other owners
        # is not checked during creation.
        if owners:
            try:
                put_res = client.session.put(
                    f"{SUPERSET_URL}/api/v1/chart/{chart_id}",
                    json={"owners": owners}
                )
                if put_res.status_code not in (200, 201):
                    raise RuntimeError(
                        f"HTTP {put_res.status_code}: "
                        + (put_res.json().get("message") or put_res.text)
                    )
            except Exception as put_err:
                logger.error(
                    "Failed to assign owner for chart %s — rolling back. Reason: %s",
                    chart_id, put_err
                )
                del_res = client.session.delete(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
                if del_res.status_code not in (200, 204):
                    logger.error(
                        "Rollback DELETE for chart %s also failed (HTTP %s): %s",
                        chart_id, del_res.status_code, del_res.text
                    )
                    return (
                        f"Chart {chart_id} was created but owner assignment failed "
                        f"({put_err}) and the automatic rollback also failed "
                        f"(HTTP {del_res.status_code}). "
                        "Please delete chart manually in Superset."
                    )
                return f"Error assigning chart ownership ({put_err}). Chart was rolled back."

        return f"Chart created and verified (renders with no error). Chart ID: {chart_id}"

    except Exception as e:
        logger.error(f"Error creating custom chart: {e}")
        return f"Error: {str(e)}"

def get_user_dashboards_and_charts(user_id: str) -> str:
    """
    Retrieves ALL charts and dashboards visible to this user:
    - can_modify=true  : charts/dashboards owned by the user (create/delete/change type).
    - can_modify=false : charts on shared dashboards (Gamma role access) that were created
                         by an admin — can be summarized, analyzed, and exported but NOT
                         deleted or modified.
    This two-tier listing is needed because the initial 'Automated Market Overview' dashboard
    is created under the admin account, so its charts have no user owner even though every
    Gamma user can see them in the iframe.
    """
    try:
        client = MCPClient()
        client.login()

        superset_user_id = _resolve_superset_user_id(client, user_id)

        # ── Step 1: Charts owned by this user (fully modifiable) ──────────────
        owned_chart_ids: set = set()
        seen_chart_ids: set = set()
        charts = []

        if superset_user_id is not None:
            filter_q = json.dumps({"filters": [{"col": "owners", "opr": "rel_m_m", "value": superset_user_id}]})
            chart_res = client.session.get(f"{SUPERSET_URL}/api/v1/chart/?q={filter_q}")
            if chart_res.status_code == 200:
                for c in chart_res.json().get("result", []):
                    cid = c["id"]
                    owned_chart_ids.add(cid)
                    seen_chart_ids.add(cid)
                    params_str = c.get("params", "{}")
                    try:
                        params = json.loads(params_str) if isinstance(params_str, str) else params_str
                    except Exception:
                        params = {}
                    charts.append({
                        "id": cid,
                        "slice_name": c["slice_name"],
                        "viz_type": c["viz_type"],
                        "metrics": params.get("metrics", []) or params.get("metric", []),
                        "groupby": params.get("groupby", []),
                        "description": c.get("description", ""),
                        "can_modify": True,
                    })

        # ── Step 2: Resolve Gamma role ID ─────────────────────────────────────
        role_res = client.session.get(
            f"{SUPERSET_URL}/api/v1/security/roles/?q="
            + json.dumps({"filters": [{"col": "name", "opr": "eq", "value": "Gamma"}]})
        )
        gamma_role_id = None
        if role_res.status_code == 200:
            roles = role_res.json().get("result", [])
            if roles:
                gamma_role_id = roles[0].get("id")

        # ── Step 3: Collect accessible dashboards + their charts ──────────────
        seen_dash_ids: set = set()
        dashboards = []

        def _ingest_dashboard_charts(dashboard_id: int) -> None:
            """Append charts from a dashboard that aren't already in the list.

            NOTE: GET /api/v1/dashboard/{id}/charts returns a different shape than
            GET /api/v1/chart/. Specifically:
              - chart params live in `form_data` (not `params`)
              - `viz_type` is inside form_data, NOT a top-level key
            Using c["viz_type"] here would raise KeyError and silently skip the
            whole dashboard via the outer except block.
            """
            try:
                res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}/charts")
                if res.status_code != 200:
                    return
                for c in res.json().get("result", []):
                    cid = c.get("id")
                    if not cid or cid in seen_chart_ids:
                        continue
                    seen_chart_ids.add(cid)
                    # form_data is the params dict for this endpoint
                    fd = c.get("form_data") or {}
                    metrics = fd.get("metrics") or []
                    if not metrics and fd.get("metric"):
                        metrics = [fd["metric"]]
                    charts.append({
                        "id": cid,
                        "slice_name": c.get("slice_name", ""),
                        "viz_type": fd.get("viz_type") or c.get("viz_type", ""),
                        "metrics": metrics,
                        "groupby": fd.get("groupby") or [],
                        "description": c.get("description", ""),
                        "can_modify": False,
                    })
            except Exception as e:
                logger.warning("Could not fetch charts for dashboard %s: %s", dashboard_id, e)

        # Dashboards accessible to the Gamma role (system/shared dashboards)
        if gamma_role_id:
            gamma_filter = json.dumps({"filters": [{"col": "roles", "opr": "rel_m_m", "value": gamma_role_id}]})
            dash_res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/?q={gamma_filter}")
            if dash_res.status_code == 200:
                for d in dash_res.json().get("result", []):
                    did = d["id"]
                    if did not in seen_dash_ids:
                        seen_dash_ids.add(did)
                        dashboards.append({"id": did, "dashboard_title": d.get("dashboard_title")})
                        _ingest_dashboard_charts(did)

        # Dashboards owned by this user (may not carry the Gamma role)
        if superset_user_id is not None:
            filter_q = json.dumps({"filters": [{"col": "owners", "opr": "rel_m_m", "value": superset_user_id}]})
            owned_dash_res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/?q={filter_q}")
            if owned_dash_res.status_code == 200:
                for d in owned_dash_res.json().get("result", []):
                    did = d["id"]
                    if did not in seen_dash_ids:
                        seen_dash_ids.add(did)
                        dashboards.append({"id": did, "dashboard_title": d.get("dashboard_title")})
                        _ingest_dashboard_charts(did)

        note = None if superset_user_id is not None else (
            "No Superset account found for this user — only charts on shared dashboards are listed."
        )
        result = {"charts": charts, "dashboards": dashboards}
        if note:
            result["note"] = note
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error fetching dashboards/charts: {e}")
        return f"Error: {str(e)}"


def _remove_chart_from_dashboards(client, chart_id: int) -> None:
    """
    Strip a chart's layout component from every dashboard it sits on, so that
    deleting the chart does not leave an orphaned "missing chart" placeholder
    ("There is no chart definition associated with this component").
    """
    try:
        res = client.session.get(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
        if res.status_code != 200:
            return
        dashboards = res.json().get("result", {}).get("dashboards", []) or []
    except Exception as e:
        logger.warning("Could not list dashboards for chart %s: %s", chart_id, e)
        return

    for d in dashboards:
        did = d.get("id")
        if not did:
            continue
        try:
            dres = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/{did}")
            if dres.status_code != 200:
                continue
            pos = json.loads(dres.json().get("result", {}).get("position_json") or "{}")

            # Components that render THIS chart.
            remove = [k for k, v in pos.items()
                      if isinstance(v, dict) and v.get("meta", {}).get("chartId") == chart_id]
            if not remove:
                continue
            for k in remove:
                pos.pop(k, None)
            # Drop references to removed components from any parent's children list.
            for v in pos.values():
                if isinstance(v, dict) and isinstance(v.get("children"), list):
                    v["children"] = [c for c in v["children"] if c not in remove]
            # Prune rows left empty, and their references, to keep the layout tidy.
            empty_rows = [k for k, v in pos.items()
                          if isinstance(v, dict) and v.get("type") == "ROW" and not v.get("children")]
            for k in empty_rows:
                pos.pop(k, None)
            for v in pos.values():
                if isinstance(v, dict) and isinstance(v.get("children"), list):
                    v["children"] = [c for c in v["children"] if c not in empty_rows]

            client.session.put(
                f"{SUPERSET_URL}/api/v1/dashboard/{did}",
                json={"position_json": json.dumps(pos)},
            )
        except Exception as e:
            logger.warning("Could not clean chart %s from dashboard %s: %s", chart_id, did, e)


def delete_chart(user_id: str, chart_id: int) -> str:
    """
    Deletes a chart, but only if it is owned by the requesting user.
    """
    try:
        client = MCPClient()
        client.login()

        res = client.session.get(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
        if res.status_code == 404:
            return f"No chart with ID {chart_id} exists."
        if res.status_code != 200:
            return f"Error fetching chart {chart_id}: HTTP {res.status_code}"

        chart = res.json().get("result", {})
        owner_ids = [o.get("id") for o in chart.get("owners", [])]
        su_id = _resolve_superset_user_id(client, user_id)
        if su_id is None or su_id not in owner_ids:
            return (
                f"Permission denied: you can only delete charts you own. "
                f"Chart {chart_id} ('{chart.get('slice_name')}') is not owned by you."
            )

        # Remove the chart from any dashboard layouts first so no orphan placeholder
        # is left behind, then delete the chart itself.
        _remove_chart_from_dashboards(client, chart_id)

        del_res = client.session.delete(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
        if del_res.status_code not in (200, 204):
            return f"Error deleting chart {chart_id}: HTTP {del_res.status_code}: {del_res.text[:200]}"
        return f"Chart {chart_id} ('{chart.get('slice_name')}') deleted and removed from its dashboard(s)."
    except Exception as e:
        logger.error(f"Error deleting chart: {e}")
        return f"Error: {str(e)}"


def delete_dashboard(user_id: str, dashboard_id: int) -> str:
    """
    Deletes a dashboard, but only if it is owned by the requesting user.
    The charts on the dashboard are not deleted.
    """
    try:
        client = MCPClient()
        client.login()

        res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}")
        if res.status_code == 404:
            return f"No dashboard with ID {dashboard_id} exists."
        if res.status_code != 200:
            return f"Error fetching dashboard {dashboard_id}: HTTP {res.status_code}"

        dash = res.json().get("result", {})
        owner_ids = [o.get("id") for o in dash.get("owners", [])]
        su_id = _resolve_superset_user_id(client, user_id)
        if su_id is None or su_id not in owner_ids:
            return (
                f"Permission denied: you can only delete dashboards you own. "
                f"Dashboard {dashboard_id} ('{dash.get('dashboard_title')}') is not owned by you."
            )

        del_res = client.session.delete(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}")
        if del_res.status_code not in (200, 204):
            return f"Error deleting dashboard {dashboard_id}: HTTP {del_res.status_code}: {del_res.text[:200]}"
        return f"Dashboard {dashboard_id} ('{dash.get('dashboard_title')}') deleted successfully."
    except Exception as e:
        logger.error(f"Error deleting dashboard: {e}")
        return f"Error: {str(e)}"

def summarize_chart(user_id: str, chart_id: int, user_role: str = "") -> str:
    """
    Fetches the data behind an existing chart so the agent can explain it in
    natural language. Data is re-computed through query_dashboard_data, so the
    SAME row-level security that protects the user elsewhere is applied here —
    a user only ever sees their own (or, for a broker, their investors') rows.

    Returns a JSON envelope: chart metadata + the RLS-filtered rows. The agent
    turns this into the prose summary.
    """
    try:
        meta, rows, error = _get_chart_rows(user_id, chart_id, user_role)
        if meta is None:
            return error
        return json.dumps({
            **meta,
            "data": rows if rows is not None else error,
            "note": (
                "These rows are already filtered to what this user is allowed to see. "
                "Summarize the key findings: lead with the headline figure, then the top and "
                "bottom values, any clear trend over time, and any outliers worth noting."
            ),
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error summarizing chart: {e}")
        return f"Error: {str(e)}"


def detect_anomalies(user_id: str, chart_id: int, user_role: str = "") -> str:
    """
    Flags statistical outliers in a chart's data using the IQR (Tukey) method.
    Reuses the RLS-safe fetch, so analysis runs only over rows the user may see.

    For every numeric metric column it computes Q1/Q3 and flags any value outside
    [Q1 - 1.5*IQR, Q3 + 1.5*IQR] as a spike or drop. Dimension columns (the chart's
    groupby/x_axis) are used to label where each anomaly occurred.
    """
    import statistics
    try:
        meta, rows, error = _get_chart_rows(user_id, chart_id, user_role)
        if meta is None:
            return error
        if error:
            return json.dumps({"chart_id": chart_id, "note": error})
        if not rows:
            return json.dumps({"chart_id": chart_id, "note": "No data available to analyze."})

        groupby = set(meta.get("groupby") or [])
        all_cols = list(rows[0].keys())
        label_cols = [c for c in all_cols if c in groupby]
        metric_cols = [c for c in all_cols if c not in groupby]

        def _num(v):
            if isinstance(v, bool):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        stats: Dict[str, Any] = {}
        anomalies: list = []
        for col in metric_cols:
            clean = [n for n in (_num(r.get(col)) for r in rows) if n is not None]
            if len(clean) < 4:
                continue  # too few points for a meaningful IQR
            q1, _q2, q3 = statistics.quantiles(clean, n=4, method="inclusive")
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            stats[col] = {
                "min": round(min(clean), 2), "max": round(max(clean), 2),
                "mean": round(statistics.fmean(clean), 2),
                "expected_range": [round(lower, 2), round(upper, 2)],
            }
            for i, r in enumerate(rows):
                v = _num(r.get(col))
                if v is None or lower <= v <= upper:
                    continue
                where = ", ".join(f"{lc}={r.get(lc)}" for lc in label_cols) or f"row {i + 1}"
                anomalies.append({
                    "where": where, "metric": col, "value": round(v, 2),
                    "type": "spike" if v > upper else "drop",
                    "expected_range": [round(lower, 2), round(upper, 2)],
                })

        return json.dumps({
            "chart_id": chart_id,
            "slice_name": meta.get("slice_name"),
            "method": "IQR (Tukey, 1.5x)",
            "rows_analyzed": len(rows),
            "metrics_analyzed": metric_cols,
            "stats": stats,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "note": (
                "If anomaly_count is 0, tell the user no statistical outliers were found. "
                "Otherwise explain each anomaly in plain language: where it occurred, its value, "
                "whether it is a spike or a drop, and the expected range it fell outside of."
            ),
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        return f"Error: {str(e)}"


_EXPORT_TTL_SECONDS = 900  # 15 minutes


def _store_csv_export(csv_text: str, filename: str):
    """
    Stash CSV content in Redis under a random token with a 15-minute TTL, so the
    Spring Boot backend can serve it later as a downloadable file. Returns the token,
    or None if Redis is unavailable (caller then falls back to inline CSV).
    """
    try:
        import redis as _redis
        import uuid as _uuid
    except Exception:
        return None
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        client = _redis.Redis.from_url(redis_url, decode_responses=True)
        token = _uuid.uuid4().hex
        pipe = client.pipeline()
        pipe.setex(f"csv_export:{token}", _EXPORT_TTL_SECONDS, csv_text)
        pipe.setex(f"csv_export:{token}:filename", _EXPORT_TTL_SECONDS, filename)
        pipe.execute()
        return token
    except Exception as e:
        logger.warning("Could not store CSV export in Redis: %s", e)
        return None


def export_chart_csv(user_id: str, chart_id: int, user_role: str = "") -> str:
    """
    Exports a chart's data (RLS-filtered) as CSV. The CSV is stored in Redis under a
    short-lived token and the tool returns a download_url to the Spring Boot backend,
    so the chat can show a clean clickable link instead of a wall of raw text.
    If Redis is unavailable it falls back to returning the CSV inline.
    """
    import io
    import csv
    try:
        meta, rows, error = _get_chart_rows(user_id, chart_id, user_role)
        if meta is None:
            return error
        if error:
            return f"Cannot export chart {chart_id}: {error}"
        if not rows:
            return f"Chart {chart_id} ('{meta.get('slice_name')}') has no data to export."

        fieldnames = list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        csv_text = buf.getvalue()

        slice_name = meta.get("slice_name") or f"chart_{chart_id}"
        safe_name = re.sub(r"[^\w\-]+", "_", slice_name).strip("_") or f"chart_{chart_id}"
        filename = f"{safe_name}.csv"

        token = _store_csv_export(csv_text, filename)
        if token:
            base = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8080").rstrip("/")
            download_url = f"{base}/api/exports/{token}"
            return json.dumps({
                "chart_id": chart_id,
                "slice_name": meta.get("slice_name"),
                "row_count": len(rows),
                "filename": filename,
                "download_url": download_url,
                "expires_in_minutes": 15,
                "note": (
                    "Give the user a clickable Markdown link exactly like "
                    f"[Download CSV]({download_url}) and mention the link expires in 15 minutes. "
                    "Do NOT paste the raw CSV."
                ),
            })

        # Fallback: Redis unavailable — return inline CSV so the feature still works.
        return json.dumps({
            "chart_id": chart_id,
            "slice_name": meta.get("slice_name"),
            "row_count": len(rows),
            "format": "csv",
            "csv": csv_text,
            "note": "Download storage is unavailable; present this CSV inside a fenced ```csv code block.",
        }, default=str)
    except Exception as e:
        logger.error(f"Error exporting chart CSV: {e}")
        return f"Error: {str(e)}"


def change_chart_type(user_id: str, chart_id: int, new_viz_type: str, user_role: str = "") -> str:
    """
    Switches an existing chart's viz_type (e.g. bar -> pie). Rebuilds the query_context
    and re-verifies the chart renders; if the new type fails, the change is reverted —
    so this can never leave a chart in the broken "Datetime column not provided" state.
    Only the chart's owner may change it.
    """
    allowed = {"echarts_timeseries_line", "echarts_timeseries_bar", "pie", "table", "big_number_total"}
    if new_viz_type not in allowed:
        return f"Invalid viz_type '{new_viz_type}'. Allowed values: {sorted(allowed)}."

    try:
        client = MCPClient()
        client.login()

        res = client.session.get(f"{SUPERSET_URL}/api/v1/chart/{chart_id}")
        if res.status_code == 404:
            return f"No chart with ID {chart_id} exists."
        if res.status_code != 200:
            return f"Error fetching chart {chart_id}: HTTP {res.status_code}"
        chart = res.json().get("result", {})

        owner_ids = [o.get("id") for o in chart.get("owners", [])]
        su_id = _resolve_superset_user_id(client, user_id)
        if su_id is None or su_id not in owner_ids:
            return (
                f"Permission denied: you can only modify charts you own. "
                f"Chart {chart_id} ('{chart.get('slice_name')}') is not owned by you."
            )

        original_params_str = chart.get("params") or "{}"
        original_qc_str = chart.get("query_context")
        try:
            params = json.loads(original_params_str)
        except Exception:
            params = {}
        original_viz = params.get("viz_type", chart.get("viz_type"))

        params["viz_type"] = new_viz_type
        # Re-shape dimension fields for the target viz type, then normalize metric
        # fields + x_axis so the chart renders. (We do not short-circuit when the type
        # is unchanged, so this can also repair a chart already saved with bad params.)
        if new_viz_type not in _TIMESERIES_VIZ:
            # pie / table / big_number use groupby, not x_axis
            x = params.pop("x_axis", None)
            gb = [c for c in (params.get("groupby") or []) if c]
            if x and x not in gb:
                gb = [x] + gb
            params["groupby"] = gb
            params.pop("time_grain_sqla", None)
        _normalize_chart_params(params)

        dataset_id = client.get_dataset_id("fact_orders")
        qc = _build_query_context(dataset_id, params)

        put = client.session.put(
            f"{SUPERSET_URL}/api/v1/chart/{chart_id}",
            json={
                "viz_type": new_viz_type,
                "params": json.dumps(params),
                "query_context": json.dumps(qc),
                "query_context_generation": True,
            },
        )
        if put.status_code not in (200, 201):
            try:
                detail = put.json().get("message") or put.text[:200]
            except Exception:
                detail = put.text[:200]
            return f"Error updating chart {chart_id}: HTTP {put.status_code}: {detail}"

        ok, verr = _verify_chart(client, chart_id)
        if not ok:
            revert = {"viz_type": original_viz, "params": original_params_str}
            if original_qc_str:
                revert["query_context"] = original_qc_str
            client.session.put(f"{SUPERSET_URL}/api/v1/chart/{chart_id}", json=revert)
            return (
                f"Switching chart {chart_id} to '{new_viz_type}' failed to render ({verr}); "
                f"the chart was reverted to '{original_viz}'. Try a different viz_type."
            )

        verb = (f"refreshed as '{new_viz_type}'" if new_viz_type == original_viz
                else f"switched from '{original_viz}' to '{new_viz_type}'")
        return (
            f"Chart {chart_id} ('{chart.get('slice_name')}') {verb} and verified. "
            f"[OPEN_CHART:{chart_id}]"
        )
    except Exception as e:
        logger.error(f"Error changing chart type: {e}")
        return f"Error: {str(e)}"


def create_custom_dashboard(user_id: str, dashboard_title: str, chart_ids: list[int]) -> str:
    """
    Creates a new Superset Dashboard containing the specified chart IDs.
    
    Args:
        user_id: The ID of the user creating the dashboard.
        dashboard_title: The title of the new dashboard.
        chart_ids: A list of integer IDs of the charts to include.
    """
    import uuid
    try:
        client = MCPClient()
        client.login()

        user_res = client.session.get(f"{SUPERSET_URL}/api/v1/security/users/?q={json.dumps({'filters':[{'col':'username','opr':'eq','value':user_id}]})}")
        owners = []
        if user_res.status_code == 200:
            users = user_res.json().get("result", [])
            if users:
                owners.append(users[0]["id"])

        role_res = client.session.get(f"{SUPERSET_URL}/api/v1/security/roles/?q={json.dumps({'filters':[{'col':'name','opr':'eq','value':'Gamma'}]})}")
        gamma_role_id = None
        if role_res.status_code == 200:
            roles = role_res.json().get("result", [])
            if roles:
                gamma_role_id = roles[0].get("id")

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

        width_per_chart = max(4, 12 // (len(chart_ids) or 1))
        chart_layout_ids = []
        for idx, cid in enumerate(chart_ids):
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
                    "chartId": cid
                }
            }
        
        position_json["ROW_1"]["children"] = chart_layout_ids

        payload = {
            "dashboard_title": dashboard_title,
            "published": True,
            "position_json": json.dumps(position_json),
            "owners": owners
        }
        
        if gamma_role_id:
            payload["roles"] = [gamma_role_id]

        response = client.session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json=payload)
        response.raise_for_status()
        dashboard_id = response.json().get("id")
        
        for cid in chart_ids:
            client.session.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dashboard_id]})

        return f"Dashboard '{dashboard_title}' created successfully with ID: {dashboard_id}"
    except Exception as e:
        logger.error(f"Error creating custom dashboard: {e}")
        return f"Error: {str(e)}"


def get_dashboard_by_name(dashboard_title: str) -> str:
    """
    Finds an existing Superset dashboard by its title and returns its ID
    plus the IDs of all charts currently on it.
    """
    try:
        client = MCPClient()
        client.login()

        filter_q = json.dumps({"filters": [{"col": "dashboard_title", "opr": "title_or_slug", "value": dashboard_title}]})
        res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/?q={filter_q}")
        if res.status_code != 200:
            return f"Error: could not search dashboards ({res.status_code})"

        results = res.json().get("result", [])
        # Match by exact title (case-insensitive)
        match = next((d for d in results if d["dashboard_title"].lower() == dashboard_title.lower()), None)
        if not match:
            return f"No dashboard found with title '{dashboard_title}'. Use create_custom_dashboard to create a new one."

        dashboard_id = match["id"]

        # Fetch charts currently on the dashboard
        charts_res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}/charts")
        chart_ids = []
        if charts_res.status_code == 200:
            chart_ids = [c["id"] for c in charts_res.json().get("result", [])]

        return json.dumps({"dashboard_id": dashboard_id, "existing_chart_ids": chart_ids})
    except Exception as e:
        logger.error(f"Error finding dashboard: {e}")
        return f"Error: {str(e)}"


def add_charts_to_existing_dashboard(dashboard_id: int, new_chart_ids: list) -> str:
    """
    Appends new charts to an existing dashboard without removing any current charts.

    Args:
        dashboard_id: The integer ID of the existing dashboard.
        new_chart_ids: List of new chart IDs to add.
    """
    import uuid
    try:
        client = MCPClient()
        client.login()

        # Fetch current position_json so we can append without destroying existing layout
        res = client.session.get(f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}")
        if res.status_code != 200:
            return f"Error: could not fetch dashboard {dashboard_id}"

        dashboard_data = res.json().get("result", {})
        position_str = dashboard_data.get("position_json") or "{}"
        try:
            position_json = json.loads(position_str)
        except Exception:
            position_json = {}

        # Ensure basic scaffold exists
        if "DASHBOARD_VERSION_KEY" not in position_json:
            position_json = {
                "DASHBOARD_VERSION_KEY": "v2",
                "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
            }

        # Add a new row for the appended charts
        new_row_id = f"ROW-{uuid.uuid4().hex[:8]}"
        position_json[new_row_id] = {
            "type": "ROW", "id": new_row_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"}
        }
        position_json["GRID_ID"]["children"].append(new_row_id)

        width = max(4, 12 // len(new_chart_ids)) if new_chart_ids else 4
        for cid in new_chart_ids:
            lid = f"CHART-{uuid.uuid4().hex[:8]}"
            position_json[lid] = {
                "type": "CHART", "id": lid, "children": [],
                "parents": ["ROOT_ID", "GRID_ID", new_row_id],
                "meta": {"width": width, "height": 50, "chartId": cid}
            }
            position_json[new_row_id]["children"].append(lid)

        # Update the dashboard with the new layout
        update_res = client.session.put(
            f"{SUPERSET_URL}/api/v1/dashboard/{dashboard_id}",
            json={"position_json": json.dumps(position_json)}
        )
        if update_res.status_code not in (200, 201):
            return f"Error updating dashboard layout: {update_res.text}"

        # Link charts to the dashboard so they appear in chart-dashboard relationships
        for cid in new_chart_ids:
            client.session.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dashboard_id]})

        return f"Successfully added {len(new_chart_ids)} chart(s) to dashboard {dashboard_id}."
    except Exception as e:
        logger.error(f"Error adding charts to dashboard: {e}")
        return f"Error: {str(e)}"
