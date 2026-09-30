"""JSON logs with secrets masked before they leave the process.

Anything that reaches a log line can end up in an external log store, so the
filter below scrubs the values this app holds that must never be stored in
the clear: webhook URLs (the path *is* the credential), push endpoints,
Canvas access tokens, bearer headers and email addresses.
"""

import json
import logging
import re
import traceback
from datetime import datetime, timezone

_PATTERNS = (
    # Discord / Slack webhooks and push-service endpoints: keep the host only.
    (
        re.compile(
            r"https://(?P<host>(?:[a-z0-9-]+\.)*(?:discord(?:app)?\.com|hooks\.slack\.com|"
            r"fcm\.googleapis\.com|jmt\d+\.google\.com|updates\.push\.services\.mozilla\.com|"
            r"web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com))/\S+",
            re.IGNORECASE,
        ),
        r"https://\g<host>/[redacted]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    # Canvas access tokens look like "<digits>~<64 chars>".
    (re.compile(r"\b\d{1,8}~[A-Za-z0-9]{20,}\b"), "[redacted-token]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[redacted-email]"),
)


def redact(text):
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


# Structured fields a caller may attach with logger.info(..., extra={...}).
_EXTRA_FIELDS = (
    "event",
    "run_id",
    "feedback_id",
    "category",
    "status",
    "safe_error_code",
    "delay_seconds",
    "deliveries",
    "courses",
    "runs",
    "exception_type",
    "stack",
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            exc_type, _exc, tb = record.exc_info
            payload["exc_type"] = exc_type.__name__
            # Frames (file/line/function/source line) only: the exception
            # *message* is dropped because it can carry a token or a URL.
            frames = "".join(traceback.format_list(traceback.extract_tb(tb)))
            payload["stack"] = redact(f"{frames}{exc_type.__name__}")
        return json.dumps(payload, ensure_ascii=False, default=str)


def logging_config(level="INFO"):
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": "config.logging.RedactingFilter"}},
        "formatters": {"json": {"()": "config.logging.JsonFormatter"}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "filters": ["redact"],
            }
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            # Request errors carry the request; the redacting filter still runs.
            "django.request": {"level": "ERROR"},
            "django.security": {"level": "WARNING"},
            "django.db.backends": {"level": "WARNING"},
        },
    }
