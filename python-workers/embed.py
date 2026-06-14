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

class SupersetEmbed:
    def __init__(self):
        self.session = requests.Session()

    def login(self):
        login_url = f"{SUPERSET_URL}/api/v1/security/login"
        payload = {"username": SUPERSET_USERNAME, "password": SUPERSET_PASSWORD, "provider": "db"}
        res = self.session.post(login_url, json=payload)
        self.session.headers.update({"Authorization": f"Bearer {res.json().get('access_token')}"})
        
        csrf_res = self.session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
        self.session.headers.update({"X-CSRFToken": csrf_res.json().get("result")})

    def embed(self):
        self.login()
        dash_id = 1
        res = self.session.post(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}/embedded", json={
            "allowed_domains": ["*"]
        })
        
        if res.status_code == 200:
            embedded_uuid = res.json().get("result", {}).get("uuid")
            print(f"SUCCESS_UUID={embedded_uuid}")
        else:
            print(f"FAILED TO EMBED: {res.status_code} {res.text}")

if __name__ == "__main__":
    SupersetEmbed().embed()
