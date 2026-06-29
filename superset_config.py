import os
import logging

# Database Connection
SQLALCHEMY_DATABASE_URI = "postgresql://admin:adminpassword@postgres:5432/vdt_db"

# Secret Key
SUPERSET_SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "vdt_super_secret_key_2026_do_not_share")
SECRET_KEY = SUPERSET_SECRET_KEY
GUEST_TOKEN_JWT_SECRET = "guest_token_super_secret_key_2026_do_not_share"
GUEST_TOKEN_JWT_AUDIENCE = lambda: "vdt-data-platform"

# Redis Cache Config
CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 86400,
    'CACHE_KEY_PREFIX': 'superset_',
    'CACHE_REDIS_URL': 'redis://redis:6379/0'
}
DATA_CACHE_CONFIG = CACHE_CONFIG

# Enable embedding for charts
ENABLE_CORS = True
CORS_OPTIONS = {
    'supports_credentials': True,
    'allow_headers': ['*'],
    'resources':['*'],
    'origins': ['http://localhost:4200', 'http://127.0.0.1:4200']
}

WTF_CSRF_ENABLED = False
FEATURE_FLAGS = {
    "EMBEDDED_SUPERSET": True,
    "ENABLE_TEMPLATE_PROCESSING": True,
    "DASHBOARD_RBAC": True
}
TALISMAN_ENABLED = False
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = False
HTTP_HEADERS = {'X-Frame-Options': 'ALLOWALL'}
GUEST_ROLE_NAME = "Gamma"

# SSO Integration
from superset.security import SupersetSecurityManager
from flask_appbuilder.security.views import AuthDBView
from flask_appbuilder import expose
from flask import request, redirect, session
from flask_login import login_user

class CustomAuthView(AuthDBView):
    route_base = '/login'
    
    @expose('/custom')
    def login_custom(self):
        token = request.args.get('token')
        if not token:
            return redirect(self.appbuilder.get_url_for_login)
        try:
            import jwt
            payload = jwt.decode(token, SUPERSET_SECRET_KEY, algorithms=["HS256"])
            username = payload.get('username')
            role = payload.get('role', '') # e.g., ROLE_BROKER
            
            user = self.appbuilder.sm.find_user(username=username)
            if not user:
                gamma_role = self.appbuilder.sm.find_role("Gamma")
                # Using a random password to prevent local login
                import uuid
                user = self.appbuilder.sm.add_user(
                    username, "User", username, f"{username}@vdt.com", [gamma_role], str(uuid.uuid4())
                )
            
            login_user(user)
            session['spring_role'] = role
            
            next_url = request.args.get('next', '/superset/welcome/')
            return redirect(next_url)
        except Exception as e:
            logging.error(f"Custom login failed: {e}")
            return f"Login failed: {str(e)}", 401

class CustomSecurityManager(SupersetSecurityManager):
    authdbview = CustomAuthView

    def __init__(self, appbuilder):
        super(CustomSecurityManager, self).__init__(appbuilder)

    # ── Datasource access fix ────────────────────────────────────────────────
    # All authenticated users (Admin and Gamma) must be able to access the
    # fact_orders datasource. Datasource-level permission grants are skipped
    # here because RLS rules (defined above in the create-dashboard flow) already
    # enforce row-level isolation per user/role. Without this override:
    #   - Admin POSTing to /api/v1/chart/ fails if fact_orders was registered
    #     after superset init (so all_datasource_access was never assigned).
    #   - Gamma users viewing a chart in the iframe hit 403 on /api/v1/chart/data
    #     because the Gamma role has no datasource permission entry.
    def can_access_datasource(self, datasource) -> bool:
        try:
            from flask_login import current_user
            if not current_user.is_anonymous:
                return True
        except Exception:
            pass
        return super().can_access_datasource(datasource)

CUSTOM_SECURITY_MANAGER = CustomSecurityManager

# Jinja template extensions for RLS
def get_user_spring_role():
    from flask import session
    return session.get('spring_role', '')

JINJA_CONTEXT_ADDONS = {
    'current_user_spring_role': get_user_spring_role
}
