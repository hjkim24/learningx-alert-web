import json
import re
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import MAX_RESPONSE_BYTES, NoRedirectHandler
from learningx_alert.network import (
    PinnedHTTPSHandler,
    UnsafeUrlError,
    validate_https_url,
)

from .models import Destination
from .services import encrypt_secret


DISCORD_PATH = re.compile(r"/api/webhooks/[0-9]+/[A-Za-z0-9._-]+")
SLACK_PATH = re.compile(r"/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9_-]+")
KST = ZoneInfo("Asia/Seoul")
MAX_MESSAGE_UNITS = 1900


class WebhookValidationError(Exception):
    pass


class DefiniteDeliveryError(Exception):
    pass


class AmbiguousDeliveryError(Exception):
    pass


@sensitive_variables()
def validate_webhook_url(kind, value, resolve_public=True):
    normalized_url = value.strip()
    providers = {
        Destination.Kind.DISCORD: ("discord.com", DISCORD_PATH),
        Destination.Kind.SLACK: ("hooks.slack.com", SLACK_PATH),
    }
    try:
        host, path_pattern = providers[kind]
        parsed = urlsplit(normalized_url)
        validate_https_url(
            normalized_url,
            {host},
            resolve_public=resolve_public,
        )
        if (
            parsed.port is not None
            or parsed.query
            or parsed.fragment
            or not path_pattern.fullmatch(parsed.path)
        ):
            raise WebhookValidationError("webhook_url_invalid")
    except (KeyError, TypeError, ValueError, UnsafeUrlError):
        raise WebhookValidationError("webhook_url_invalid") from None
    return normalized_url


def _safe_external_text(value):
    return " ".join(str(value).split()).replace("@", "＠").replace("<", "‹").replace(">", "›")


def render_notification(result, now):
    lines = [f"LearningX Alert · {now.astimezone(KST):%Y.%m.%d %H:%M} KST"]
    items = sorted(result.items, key=lambda item: item.due_at)
    if items:
        lines.append("")
        for item in items:
            item_type = "과제" if item.item_type == "assignment" else "알림"
            lines.extend(
                (
                    f"[{item_type}] {_safe_external_text(item.course_name)} · {_safe_external_text(item.title)}",
                    f"마감 {item.due_at.astimezone(KST):%Y.%m.%d %H:%M} KST",
                )
            )
    else:
        lines.extend(("", "현재 조회 범위에 알림 대상 과제가 없습니다."))

    failures = [outcome for outcome in result.outcomes if outcome.status == "failed"]
    if failures:
        lines.extend(("", "조회 실패"))
        for outcome in failures:
            lines.append(
                f"- {_safe_external_text(outcome.course_name)}: "
                f"{outcome.safe_summary} ({outcome.error_code})"
            )
    return "\n".join(lines)


def _utf16_units(value):
    return len(value.encode("utf-16-le")) // 2


def split_message(text):
    parts = []
    remaining = text
    while _utf16_units(remaining) > MAX_MESSAGE_UNITS:
        units = 0
        cutoff = 0
        for cutoff, character in enumerate(remaining, start=1):
            next_units = units + _utf16_units(character)
            if next_units > MAX_MESSAGE_UNITS:
                cutoff -= 1
                break
            units = next_units
        preferred = remaining.rfind("\n", 0, cutoff)
        if preferred > 0:
            cutoff = preferred + 1
        parts.append(remaining[:cutoff])
        remaining = remaining[cutoff:]
    parts.append(remaining)
    return tuple(parts)


def _delivery_opener(resolve_public):
    handlers = [ProxyHandler({}), NoRedirectHandler()]
    if resolve_public:
        handlers.append(PinnedHTTPSHandler())
    return build_opener(*handlers)


@sensitive_variables()
def send_webhook_part(
    kind,
    webhook_url,
    text,
    opener=None,
    resolve_public=True,
):
    normalized_url = validate_webhook_url(
        kind,
        webhook_url,
        resolve_public=resolve_public,
    )
    if kind == Destination.Kind.DISCORD:
        request_url = f"{normalized_url}?wait=true"
        payload = {"content": text, "allowed_mentions": {"parse": []}}
    else:
        request_url = normalized_url
        payload = {"text": text}
    request = Request(
        request_url,
        data=json.dumps(payload).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    delivery_opener = opener or _delivery_opener(resolve_public)

    try:
        response = delivery_opener.open(request, timeout=30)
    except HTTPError:
        raise DefiniteDeliveryError("webhook_rejected") from None
    except (URLError, TimeoutError, ConnectionError, UnsafeUrlError, OSError):
        raise AmbiguousDeliveryError("delivery_outcome_unknown") from None

    try:
        with response:
            if response.geturl() != request_url:
                raise AmbiguousDeliveryError("delivery_outcome_unknown")
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise DefiniteDeliveryError("webhook_rejected")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AmbiguousDeliveryError("delivery_outcome_unknown")
    except (DefiniteDeliveryError, AmbiguousDeliveryError):
        raise
    except (URLError, TimeoutError, ConnectionError, OSError, ValueError):
        raise AmbiguousDeliveryError("delivery_outcome_unknown") from None

    if kind == Destination.Kind.SLACK:
        if status != 200 or body.strip() != b"ok":
            raise AmbiguousDeliveryError("delivery_outcome_unknown")
        return "ok"

    try:
        confirmation = json.loads(body)
        receipt = confirmation["id"]
        if not isinstance(receipt, str) or not receipt:
            raise ValueError
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise AmbiguousDeliveryError("delivery_outcome_unknown") from None
    return receipt


@sensitive_variables("webhook_url", "normalized_url")
def save_destination(user, kind, webhook_url):
    normalized_url = validate_webhook_url(kind, webhook_url)
    destination, _ = Destination.objects.update_or_create(
        user=user,
        defaults={
            "kind": kind,
            "encrypted_webhook_url": encrypt_secret(normalized_url),
            "status": Destination.Status.UNTESTED,
            "last_tested_at": None,
        },
    )
    return destination
