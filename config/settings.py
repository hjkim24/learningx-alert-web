import os
from pathlib import Path

from cryptography.fernet import Fernet

from config.logging import logging_config


BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_setting(name: str) -> str:
    file_variable = f"{name}_FILE"
    file_path = os.environ.get(file_variable, "").strip()
    if not file_path:
        return os.environ.get(name, "")
    try:
        value = Path(file_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise RuntimeError(
            f"{file_variable} must reference a readable non-empty UTF-8 file"
        ) from None
    if not value:
        raise RuntimeError(
            f"{file_variable} must reference a readable non-empty UTF-8 file"
        )
    return value


DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
DJANGO_SECRET_KEY = _secret_setting("DJANGO_SECRET_KEY")
SECRET_KEY = DJANGO_SECRET_KEY or "local-development-only"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True
LANGUAGE_CODE = "ko-kr"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_EXCEPTION_REPORTER_FILTER = "config.filters.AlwaysSafeExceptionReporterFilter"
TEST_RUNNER = "config.test_runner.AppTestRunner"
LOGGING = logging_config(os.environ.get("LOG_LEVEL", "INFO").upper())
RATE_LIMITS_ENABLED = True

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "accounts",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.csp.ContentSecurityPolicyReportOnlyMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
# Report-only CSP: nothing is blocked, violations are logged via /csp-report/.
CSP_REPORT_ONLY = os.environ.get("CSP_REPORT_ONLY", "1") == "1"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.assets",
            ]
        },
    }
]
DATABASE_ENGINE = os.environ.get("DATABASE_ENGINE", "sqlite").strip().lower()
if DATABASE_ENGINE == "mysql":
    # PyMySQL is pure Python (no C build in the image) and stands in for mysqlclient.
    import pymysql

    pymysql.install_as_MySQLdb()
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "HOST": os.environ.get("DATABASE_HOST", ""),
            "PORT": os.environ.get("DATABASE_PORT", "3306"),
            "NAME": os.environ.get("DATABASE_NAME", "learningx_alert"),
            "USER": os.environ.get("DATABASE_USER", "learningx"),
            "PASSWORD": _secret_setting("DATABASE_PASSWORD"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
                # MySQL HeatWave only accepts TLS; the traffic stays inside the VCN.
                "ssl": {"ssl": True},
            },
            "TEST": {"NAME": "test_learningx_alert", "CHARSET": "utf8mb4"},
        }
    }
elif DATABASE_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }
else:
    raise RuntimeError("DATABASE_ENGINE must be 'sqlite' or 'mysql'")
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Production serves content-hashed copies (app.3f2a….css) that Caddy may cache
# for a year. The image build runs collectstatic with STATIC_MANIFEST=1; local
# development and tests keep plain names so they never need collectstatic.
STATIC_MANIFEST = os.environ.get("STATIC_MANIFEST", "0" if DEBUG else "1") == "1"
if STATIC_MANIFEST:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        },
    }
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "account_login"
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
SOCIALACCOUNT_ONLY = True
ACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = False
# Open sign-up: any Google account with a verified email may join. Off unless
# explicitly "1", so a missing or mistyped value keeps the allowlist gate.
SIGNUP_OPEN = os.environ.get("SIGNUP_OPEN", "0") == "1"
# Open sign-up creates at most this many accounts in total (0 = no cap).
SIGNUP_MAX_USERS = int(os.environ.get("SIGNUP_MAX_USERS", "100"))
PILOT_ALLOWED_EMAILS = {
    email.strip().casefold()
    for email in os.environ.get("PILOT_ALLOWED_EMAILS", "").split(",")
    if email.strip()
}
SOCIALACCOUNT_ADAPTER = "accounts.adapters.PilotSocialAccountAdapter"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = _secret_setting("GOOGLE_CLIENT_SECRET")
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_CLIENT_SECRET,
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
    }
}
# Public contact shown on /privacy/ (the Google consent screen links there).
PRIVACY_CONTACT_EMAIL = os.environ.get("PRIVACY_CONTACT_EMAIL", "").strip()
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "https://canvas.skku.edu")
# Hosts the LearningX LTI launch may visit. Empty disables lecture alerts.
LEARNINGX_ALLOWED_HOSTS = frozenset(
    host.strip().lower()
    for host in os.environ.get("LEARNINGX_ALLOWED_HOSTS", "").split(",")
    if host.strip()
)
# Browser (PWA) push. The VAPID key is derived from SECRET_KEY unless an explicit
# base64url P-256 scalar is provided; the subject is the contact push services see.
WEB_PUSH_ENABLED = os.environ.get("WEB_PUSH_ENABLED", "1") == "1"
WEB_PUSH_VAPID_PRIVATE_KEY = _secret_setting("WEB_PUSH_VAPID_PRIVATE_KEY")
WEB_PUSH_SUBJECT = os.environ.get("WEB_PUSH_SUBJECT", "").strip() or (
    f"https://{ALLOWED_HOSTS[0]}"
    if ALLOWED_HOSTS and ALLOWED_HOSTS[0] not in {"127.0.0.1", "localhost"}
    else "https://alert.sobok-app.com"
)
CREDENTIAL_ENCRYPTION_KEYS = [
    key.strip()
    for key in _secret_setting("CREDENTIAL_ENCRYPTION_KEYS").split(",")
    if key.strip()
]

if not DEBUG:
    required_production_settings = {
        "DJANGO_SECRET_KEY": DJANGO_SECRET_KEY,
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "CREDENTIAL_ENCRYPTION_KEYS": CREDENTIAL_ENCRYPTION_KEYS,
    }
    missing = [name for name, value in required_production_settings.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required production configuration: " + ", ".join(missing)
        )
    try:
        for key in CREDENTIAL_ENCRYPTION_KEYS:
            Fernet(key.encode())
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEYS must contain valid Fernet keys"
        ) from error

SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# HSTS starts short on purpose: browsers remember it for max-age and it cannot
# be recalled, so raise it (e.g. 31536000) only after it has run cleanly. No
# includeSubDomains/preload: other sobok-app.com hosts must not be bound.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0" if DEBUG else "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
