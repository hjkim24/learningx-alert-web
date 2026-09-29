import os
from pathlib import Path

from cryptography.fernet import Fernet


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
    "allauth.account.middleware.AccountMiddleware",
]
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
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
    }
}
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "account_login"
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
SOCIALACCOUNT_ONLY = True
ACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = False
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
