# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VDT Data Platform is a full-stack enterprise data platform featuring an **Agentic AI chatbot** and embedded **Apache Superset** dashboards. Users authenticate via the Angular frontend, query stock market data in natural language, and view Superset visualizations rendered inside an iframe via SSO.

## Services & Ports

| Service | Port | Notes |
|---|---|---|
| Angular Frontend | 4200 | Served by Nginx in Docker |
| Spring Boot Backend | 8080 | JWT-secured REST API |
| Apache Superset | 8088 | Admin: `admin` / `admin` |
| FastAPI Python Worker | 8000 | AI agent + dashboard automation |
| PostgreSQL | 5432 | User: `admin`, Pass: `adminpassword`, DB: `vdt_db` |
| Redis | 6379 | Used by Superset for caching AND by Python Worker for CSV export storage |

## Quick Start (Docker)

```bash
# Create .env in project root with required secrets
echo "SUPERSET_SECRET_KEY=your_secret" > .env
echo "CODEX_API_KEY=your_key" >> .env
echo "CODEX_BASE_URL=your_base_url" >> .env
echo "CODEX_MODEL=gpt-5.4" >> .env
echo "INTERNAL_API_KEY=change-this-in-production" >> .env
echo "BACKEND_PUBLIC_URL=http://localhost:8080" >> .env

docker-compose up --build -d
docker-compose logs -f
docker-compose down

# Rebuild only changed services (faster iteration):
docker-compose up -d --no-deps --build python-worker backend
```

## Local Development Commands

**Frontend (Angular 18)**
```bash
cd frontend
npm install
npm start          # dev server at http://localhost:4200
npm run build      # production build
ng test            # unit tests (Karma)
```

**Backend (Spring Boot 3 / Java 17)**
```bash
cd backend
mvn clean spring-boot:run
# Requires local PostgreSQL on port 5432 with vdt_db database
# Requires local Redis on port 6379 (for CSV export endpoint)
```

**Python Worker (FastAPI)**
```bash
cd python-workers
pip install -r requirements.txt
python main.py     # starts on http://localhost:8000
# Interactive API docs at http://localhost:8000/docs
```

**E2E Tests (Playwright)**
```bash
cd e2e_tests
npm install
npx playwright install chromium
npx playwright test chatbot.spec.ts
# Requires all services running on their standard ports
```

## Required Environment Variables

**Root `.env` (for Docker Compose):**
- `SUPERSET_SECRET_KEY` — must match `superset_config.py`; used to sign SSO JWTs
- `CODEX_API_KEY` — OpenAI-compatible API key for the AI agent
- `CODEX_BASE_URL` — base URL for the AI API (if not standard OpenAI)
- `CODEX_MODEL` — model name to use (default: `gpt-5.4`); was previously hardcoded as `gpt-5.4-mini`
- `INTERNAL_API_KEY` — shared secret between Spring Boot and the Python Worker (`X-Internal-Api-Key` header)
- `BACKEND_PUBLIC_URL` — browser-visible URL of the Spring Boot backend (default: `http://localhost:8080`); used to build CSV download links returned by `export_chart_csv`

**Backend (`application.yml` or env):**
- `SUPERSET_SECRET_KEY`, `CODEX_API_KEY`, `SUPERSET_URL`, `AUTOMATION_WORKER_URL`
- `SPRING_DATASOURCE_URL/USERNAME/PASSWORD`
- `REDIS_HOST`, `REDIS_PORT` — for the CSV export `ExportController` (set to `redis`/`6379` in Docker)

**Frontend (`frontend/src/environments/environment.ts`):**
- `BACKEND_API_URL` — defaults to `http://localhost:8080/api`
- `SUPERSET_DOMAIN` — defaults to `http://localhost:8088`

## Architecture & Key Data Flows

### Authentication Flow
1. Angular `LoginComponent` POSTs credentials to `POST /api/auth/login`
2. Spring `AuthController` validates against `users` table (BCrypt passwords), returns a JWT
3. Angular stores the JWT; `AuthInterceptor` injects `Authorization: Bearer <token>` on all subsequent requests
4. `AuthTokenFilter` (Spring Security) validates the JWT on every protected endpoint

### Chat / AI Agent Flow
1. Angular `DashboardComponent.sendChat()` POSTs `{ sessionId, query }` to `POST /api/chat/query`
2. Spring `ChatController` resolves the username from the JWT principal, delegates to `ChatService`
3. `ChatService` persists the user message, then calls `POST /api/chat` on the **Python Worker** (authenticated via `X-Internal-Api-Key` header)
4. The Python Worker (`main.py`) runs an agentic loop using the OpenAI-compatible API (model set by `CODEX_MODEL` env var) with 13 Superset tools defined in `mcp_superset.py`:
   - `get_superset_schema` — fetches live schema from Superset datasets API (cached 5 min)
   - `query_dashboard_data` — queries `fact_orders` **directly via PostgreSQL** with parameterized RLS
   - `create_custom_chart` — creates a verified chart in Superset via REST (rolls back on render failure)
   - `get_user_dashboards_and_charts` — lists charts/dashboards owned by this user
   - `create_custom_dashboard` — creates a dashboard and grants Gamma role access
   - `get_dashboard_by_name` — finds an existing dashboard by title
   - `add_charts_to_existing_dashboard` — appends charts to an existing dashboard layout
   - `summarize_chart` — fetches RLS-filtered chart data for the AI to narrate as prose
   - `detect_anomalies` — IQR (Tukey 1.5×) outlier detection on chart data
   - `export_chart_csv` — exports RLS-filtered chart data via Redis + Spring Boot download link
   - `change_chart_type` — switches viz_type, rebuilds query_context, reverts on render failure
   - `delete_chart` — ownership-checked deletion; removes layout component from dashboards first
   - `delete_dashboard` — ownership-checked deletion; charts are kept
5. If the AI reply contains `[OPEN_CHART:<id>]` or `[OPEN_DASHBOARD:<id>]`, the frontend parses it and navigates the Superset iframe to that chart/dashboard URL

### CSV Export Flow
1. User asks chatbot to export a chart
2. Python Worker `export_chart_csv` fetches RLS-filtered rows via `query_dashboard_data`
3. Rows are serialized to CSV and stored in Redis under `csv_export:{token}` with 15-min TTL (`SETEX`)
4. Tool returns `{ download_url: "http://localhost:8080/api/exports/{token}" }`
5. AI renders a Markdown link: `[Download CSV](url)` — no raw data in the chat
6. Browser hits `GET /api/exports/{token}` on Spring Boot `ExportController`
7. Controller reads CSV from Redis, prepends UTF-8 BOM (for Excel Vietnamese compatibility), returns as `attachment; filename="..."`
8. Link is public (`/api/exports/**` is `permitAll()` in SecurityConfig) — the unguessable token + 15-min TTL is the capability. Data is already RLS-filtered at export time.

### Superset SSO Embedding
1. Angular calls `GET /api/superset/sso-login` (auth required)
2. Spring `SupersetController` calls `SupersetService.getSsoToken()` which generates a JWT signed with `SUPERSET_SECRET_KEY`
3. The frontend loads `http://localhost:8088/login/custom?token=<jwt>&next=/superset/welcome/` inside an `<iframe>`, giving the user a seamless Superset session under their identity
4. Dashboard creation is triggered lazily: `SupersetService.getDashboardUuid()` calls the Python Worker's `POST /api/create-dashboard` and caches the result in memory

### Row-Level Security (RLS)
- RLS is enforced at **two layers**:
  - **Superset layer**: native RLS rule on `fact_orders` for the Gamma role, Jinja2 clause filters by `investor_id` / broker's investors
  - **Python worker layer**: `query_dashboard_data` and all analyst tools (`summarize_chart`, `detect_anomalies`, `export_chart_csv`) query PostgreSQL directly with parameterized `WHERE investor_id = %s` — the AI model only ever sees the user's own rows
- The model cannot bypass RLS because SQL is constructed in Python, not by the model

## Database Schema (Star Schema — `vdt_db`)

- `dim_tickers` — listed securities (id, symbol, company_name, sector)
- `dim_brokers` — broker managers (broker_id, name)
- `dim_investors` — client investors, mapped to broker (investor_id, broker_id, name)
- `fact_orders` — trades (order_id, order_date, investor_id, ticker_id, order_type, volume, price, **status**)
  - `status` values: `Khớp` (filled), `Chờ` (pending), `Hủy` (cancelled)
- `users` — platform auth accounts linked to Spring roles
- `chat_sessions`, `chat_messages` — chat history (sessionId, username, content, senderType, createdAt)

## Frontend Structure

The Angular app uses **standalone components** with lazy-loaded routes:
- `/login` → `LoginComponent` — credential form
- `/dashboard` → `DashboardComponent` — chatbot panel + Superset iframe side-by-side

The `DashboardComponent` owns the full chat state (messages array, sessionId via `crypto.randomUUID()`) and the iframe URL. There is no NgRx/state management library — state lives in the component.

`AuthService` stores the JWT in `localStorage`. `ApiService` provides the base HTTP helper; `ChatService` handles chat API calls.

## Key Implementation Details

### Superset Chart Creation (`create_custom_chart`)
- Calls `_normalize_chart_params` before creation:
  - `pie` / `big_number_total` require singular `metric` field; all others require `metrics` list — mismatch causes frontend "Cannot read properties of undefined (reading 'label')"
  - `echarts_timeseries_*` require `x_axis`; if missing, first `groupby` column is promoted to `x_axis`; non-temporal x_axis causes `time_grain_sqla` to be dropped
- Saves `query_context` explicitly after creation — API-created charts lack it, causing "Datetime column not provided" in dashboard render
- Calls `_verify_chart` (GET `/api/v1/chart/{id}/data/`) after creation; rolls back (DELETE) on failure
- Adds user as chart owner in a separate follow-up PUT to avoid Superset 4.x ownership validation bug

### Gamma Role Datasource Permissions
- `_grant_gamma_datasource_access(dataset_id)` writes directly to `ab_permission_view_role` via psycopg2
- FAB's REST RoleApi cannot edit role permissions (`edit_columns` only exposes `name`)
- Without this grant, adding a Gamma user as chart owner causes 403 FORBIDDEN
- Uses `ON CONFLICT (permission_view_id, role_id) DO NOTHING` — idempotent

### `superset_config.py` — `can_access_datasource` Override
- Uses `flask_login.current_user.is_anonymous` (not `g.get("user")`)
- `g.user` is None for JWT Bearer requests (API calls); `flask_login.current_user` is always populated
- All authenticated Superset users get datasource access; RLS handles row-level isolation

### SQL Security in `query_dashboard_data`
- `_validate_sql_expression`: only `AGGREGATE([DISTINCT] column)` patterns allowed; blocks semicolons, DDL keywords, system tables
- `_safe_identifier`: rejects any column/identifier containing non-word characters
- `_validate_columns`: pre-flight check against live Superset schema before query execution

### Codex / AI Privacy Consideration
- All users share a single `CODEX_API_KEY` — the Codex provider sees all users' natural language queries associated with one key
- **Data rows** are never exposed cross-user: RLS is applied before any data reaches the model
- **Query intent** (natural language) is exposed to the provider; consider Azure OpenAI with DPA or self-hosted model for finance-grade privacy
- Each API call is stateless; no in-process cross-user contamination

## Important Caveats

- The AI model is configured via `CODEX_MODEL` env var (default: `gpt-5.4`) — must be a valid model at `CODEX_BASE_URL`
- `SupersetService.getDashboardUuid()` caches the dashboard ID in a plain Java instance field — a backend restart resets this cache and triggers a new dashboard creation call
- CORS in `SecurityConfig` only allows `http://localhost:4200` — update `allowedOrigins` for any other frontend origin
- The `superset_config.py` at the project root is volume-mounted into the Superset containers and must define `SECRET_KEY` matching `SUPERSET_SECRET_KEY`
- CSV export links are public capability URLs (`/api/exports/{token}`) — secure by unguessable UUID token + 15-min Redis TTL. To add one-time-use deletion, add `redisTemplate.delete(KEY_PREFIX + token)` after the first successful read in `ExportController`
- `_schema_cache` in `mcp_superset.py` is process-global (shared across all requests) — refreshes every 5 minutes; only contains column metadata, not row data
