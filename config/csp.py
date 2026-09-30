"""Content-Security-Policy in report-only mode, plus the endpoint that logs reports.

Report-only never blocks anything: browsers only tell us what the policy
*would* have blocked. Once the log stays quiet for a while, the same policy can
be sent as the enforcing ``Content-Security-Policy`` header instead.
"""

import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("config.csp")

REPORT_PATH = "/csp-report/"
MAX_REPORT_BYTES = 8 * 1024

POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        # The Google sign-in form posts here and is redirected to Google.
        "form-action 'self' https://accounts.google.com",
        f"report-uri {REPORT_PATH}",
    )
)


class ContentSecurityPolicyReportOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.CSP_REPORT_ONLY and "Content-Security-Policy-Report-Only" not in response:
            response["Content-Security-Policy-Report-Only"] = POLICY
        return response


def _blocked_label(value):
    """Reduce a blocked URI to something safe to log: a keyword or an origin."""
    value = str(value or "")
    if value in {"inline", "eval", "data", "blob", "self", "wasm-eval", "trusted-types-policy"}:
        return value
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return f"{parts.scheme}://{parts.hostname}"
    return parts.scheme or "other"


def _page_path(value):
    return urlsplit(str(value or "")).path[:200] or "-"


@csrf_exempt
@require_POST
def report(request):
    """Log one CSP violation report. Anonymous by design: browsers send these
    without cookies, so the body is size-capped and reduced before logging."""
    if len(request.body) > MAX_REPORT_BYTES:
        return HttpResponse(status=413)
    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=400)
    body = payload.get("csp-report", payload) if isinstance(payload, dict) else {}
    if not isinstance(body, dict):
        return HttpResponse(status=400)
    directive = str(
        body.get("effective-directive") or body.get("violated-directive") or "-"
    ).split(" ")[0][:60]
    logger.warning(
        "csp violation directive=%s blocked=%s page=%s",
        directive,
        _blocked_label(body.get("blocked-uri")),
        _page_path(body.get("document-uri")),
        extra={"event": "csp_violation"},
    )
    return HttpResponse(status=204)
