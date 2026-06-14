import os

# Database Connection
SQLALCHEMY_DATABASE_URI = "postgresql://admin:adminpassword@postgres:5432/vdt_db"

# Secret Key
SUPERSET_SECRET_KEY = "vdt_super_secret_key_2026_do_not_share"
SECRET_KEY = SUPERSET_SECRET_KEY

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
    'origins': ['*']
}

WTF_CSRF_ENABLED = False
FEATURE_FLAGS = {
    "EMBEDDED_SUPERSET": True
}
TALISMAN_ENABLED = False
SESSION_COOKIE_SAMESITE = None
GUEST_ROLE_NAME = "Public"
