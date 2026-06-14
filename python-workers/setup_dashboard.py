import requests
import json
import logging
import uuid
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPERSET_URL = "http://localhost:8088"
SUPERSET_USERNAME = "admin"
SUPERSET_PASSWORD = "admin"

class SupersetSetup:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        login_url = f"{SUPERSET_URL}/api/v1/security/login"
        payload = {"username": SUPERSET_USERNAME, "password": SUPERSET_PASSWORD, "provider": "db"}
        res = self.session.post(login_url, json=payload)
        self.session.headers.update({"Authorization": f"Bearer {res.json().get('access_token')}"})
        
        csrf_res = self.session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
        self.session.headers.update({"X-CSRFToken": csrf_res.json().get("result")})

    def setup(self):
        self.login()

        # Get DB
        res = self.session.get(f"{SUPERSET_URL}/api/v1/database/")
        dbs = [db for db in res.json().get("result", []) if db["database_name"] == "vdt_db"]
        if not dbs:
            res = self.session.post(f"{SUPERSET_URL}/api/v1/database/", json={
                "database_name": "vdt_db",
                "sqlalchemy_uri": "postgresql://admin:adminpassword@postgres:5432/vdt_db"
            })
            db_id = res.json().get("id")
        else:
            db_id = dbs[0]["id"]

        # Get Dataset
        res = self.session.get(f"{SUPERSET_URL}/api/v1/dataset/")
        datasets = [ds for ds in res.json().get("result", []) if ds["table_name"] == "fact_orders"]
        if not datasets:
            res = self.session.post(f"{SUPERSET_URL}/api/v1/dataset/", json={
                "database": db_id, "table_name": "fact_orders", "schema": "public"
            })
            ds_id = res.json().get("id")
        else:
            ds_id = datasets[0]["id"]

        # Create Dashboard
        dashboard_title = "Automated Market Overview"
        
        position_json = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
            "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        }
        
        res = self.session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json={
            "dashboard_title": dashboard_title,
            "published": True,
            "position_json": json.dumps(position_json)
        })
        dash_id = res.json().get("id")

        # Enable Embedding
        res = self.session.post(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}/embedded/", json={
            "allowed_domains": ["*"]
        })
        
        if res.status_code == 200:
            embedded_uuid = res.json().get("result", {}).get("uuid")
            print(f"SUCCESS_UUID={embedded_uuid}")
        else:
            print(f"FAILED TO EMBED: {res.text}")

if __name__ == "__main__":
    SupersetSetup().setup()
