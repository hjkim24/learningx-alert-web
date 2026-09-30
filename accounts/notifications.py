import hashlib
import hmac
import json
import re
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import MAX_RESPONSE_BYTES, NoRedirectHandler
from learningx_alert.network import (
    PinnedHTTPSHandler,
    UnsafeUrlError,
    validate_https_url,
)

from . import webpush
from .templatetags.course_names import split_course_name
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


class SubscriptionGoneError(DefiniteDeliveryError):
    """The push service says the browser subscription no longer exists."""


class DestinationLimitError(Exception):
    pass


class DuplicateDestinationError(Exception):
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


ITEM_TYPE_LABELS = {"assignment": "과제", "quiz": "퀴즈", "lecture": "강의", "material": "학습자료"}


WEEKDAYS_KO = ("월", "화", "수", "목", "금", "토", "일")


def _day_heading(day, today):
    delta = (day - today).days
    dday = "오늘" if delta == 0 else f"D-{delta}" if delta > 0 else f"D+{-delta}"
    return f"■ {day.month}월 {day.day}일 ({WEEKDAYS_KO[day.weekday()]}) · {dday}"


def _group_by_day_and_course(items):
    """[(day, [(course_title, [items...]), ...]), ...], each level by earliest due."""
    days = {}
    for item in sorted(items, key=lambda entry: entry.due_at):
        day = item.due_at.astimezone(KST).date()
        title = split_course_name(item.course_name)["title"] or item.course_name
        courses = days.setdefault(day, {})
        courses.setdefault((item.canvas_course_id, title), []).append(item)
    return [
        (day, [(title, entries) for (_course_id, title), entries in courses.items()])
        for day, courses in days.items()
    ]


def render_notification(result, now):
    """Chat message: items grouped by KST due date, then by course."""
    local_now = now.astimezone(KST)
    items = list(result.items)
    lines = [f"LearningX Alert · {local_now:%Y.%m.%d %H:%M} KST"]
    if items:
        lines.append(f"마감 {len(items)}건")
        for day, courses in _group_by_day_and_course(items):
            lines.extend(("", _day_heading(day, local_now.date())))
            for title, entries in courses:
                lines.append(_safe_external_text(title))
                for item in entries:
                    item_type = ITEM_TYPE_LABELS.get(item.item_type, "알림")
                    lines.append(
                        f"- [{item_type}] {_safe_external_text(item.title)} · "
                        f"{item.due_at.astimezone(KST):%H:%M}"
                    )
    else:
        lines.extend(("", "조회 기간 안에 마감되는 과제·강의가 없어요."))

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


def target_fingerprint(kind, secret_target):
    """Keyed, non-reversible identity of a webhook URL or push endpoint."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"{kind}:{secret_target}".encode(),
        hashlib.sha256,
    ).hexdigest()


@sensitive_variables()
def _create_destination(user, kind, secret, fingerprint, label=""):
    try:
        with transaction.atomic():
            # MySQL cannot enforce the conditional unique constraint on
            # target_fingerprint, so serialise per user: a concurrent second
            # request waits here and then sees the first one's row.
            get_user_model().objects.select_for_update().filter(pk=user.pk).exists()
            if Destination.objects.filter(user=user, target_fingerprint=fingerprint).exists():
                raise DuplicateDestinationError
            if Destination.objects.filter(user=user).count() >= Destination.MAX_PER_USER:
                raise DestinationLimitError
            return Destination.objects.create(
                user=user,
                kind=kind,
                label=label[:64],
                encrypted_webhook_url=encrypt_secret(secret),
                target_fingerprint=fingerprint,
            )
    except IntegrityError:
        raise DuplicateDestinationError from None


@sensitive_variables("webhook_url", "normalized_url")
def save_destination(user, kind, webhook_url, label=""):
    """Add a Discord/Slack webhook as a new destination for the user."""
    normalized_url = validate_webhook_url(kind, webhook_url)
    return _create_destination(
        user,
        kind,
        normalized_url,
        target_fingerprint(kind, normalized_url),
        label,
    )


@sensitive_variables()
def save_push_subscription(user, subscription, label=""):
    """Register (or refresh) this browser's push subscription."""
    normalized = webpush.normalize_subscription(subscription)
    fingerprint = target_fingerprint(Destination.Kind.WEBPUSH, normalized["endpoint"])
    existing = Destination.objects.filter(
        user=user,
        target_fingerprint=fingerprint,
    ).first()
    if existing:
        # Same endpoint, possibly rotated keys: refresh in place.
        existing.encrypted_webhook_url = encrypt_secret(json.dumps(normalized))
        if label:
            existing.label = label[:64]
        existing.save(update_fields=("encrypted_webhook_url", "label"))
        return existing, False
    return (
        _create_destination(
            user,
            Destination.Kind.WEBPUSH,
            json.dumps(normalized),
            fingerprint,
            label,
        ),
        True,
    )


def render_push_notification(result, now):
    """Short title/body for a browser notification (one push record)."""
    items = sorted(result.items, key=lambda item: item.due_at)
    failures = [outcome for outcome in result.outcomes if outcome.status == "failed"]
    if items:
        title = f"마감 알림 {len(items)}건"
        lines = []
        for item in items[:4]:
            item_type = ITEM_TYPE_LABELS.get(item.item_type, "알림")
            lines.append(
                f"[{item_type}] {_safe_external_text(item.title)} · "
                f"{item.due_at.astimezone(KST):%m.%d %H:%M}"
            )
        if len(items) > 4:
            lines.append(f"외 {len(items) - 4}건")
    else:
        title = "마감 알림"
        lines = ["조회 기간 안에 마감되는 과제·강의가 없어요."]
    if failures:
        lines.append(f"조회 실패 과목 {len(failures)}개")
    return webpush.push_payload(f"LearningX Alert · {title}", "\n".join(lines))


def message_parts(kind, result, now):
    """What one destination receives for a run: chat parts or a single push."""
    if kind == Destination.Kind.WEBPUSH:
        return (render_push_notification(result, now).decode(),)
    return split_message(render_notification(result, now))


TEST_MESSAGE = "LearningX Alert 시험 알림이에요."


def test_message_for(kind):
    if kind == Destination.Kind.WEBPUSH:
        return webpush.push_payload(
            "LearningX Alert", "시험 알림이에요. 이 기기로 알림을 받을 수 있어요."
        ).decode()
    return TEST_MESSAGE


@sensitive_variables()
def send_web_push(subscription_json, payload, opener=None, resolve_public=True):
    try:
        subscription = json.loads(subscription_json)
        endpoint = webpush.validate_push_endpoint(
            subscription["endpoint"],
            resolve_public=resolve_public,
        )
        body = webpush.encrypt_payload(
            payload.encode(),
            subscription["keys"]["p256dh"],
            subscription["keys"]["auth"],
        )
    except (KeyError, TypeError, ValueError, webpush.PushValidationError):
        raise DefiniteDeliveryError("push_subscription_invalid") from None
    request = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": webpush.vapid_authorization(endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(webpush.PUSH_TTL_SECONDS),
            "Urgency": "high",
        },
        method="POST",
    )
    delivery_opener = opener or _delivery_opener(resolve_public)
    try:
        response = delivery_opener.open(request, timeout=30)
    except HTTPError as error:
        if error.code in (404, 410):
            raise SubscriptionGoneError("push_subscription_gone") from None
        raise DefiniteDeliveryError("push_rejected") from None
    except (URLError, TimeoutError, ConnectionError, UnsafeUrlError, OSError):
        raise AmbiguousDeliveryError("delivery_outcome_unknown") from None
    with response:
        status = getattr(response, "status", 201)
        if not 200 <= status < 300:
            raise DefiniteDeliveryError("push_rejected")
        # The push service returns the message resource in Location (RFC 8030).
        location = response.headers.get("Location", "") if response.headers else ""
    return location.rsplit("/", 1)[-1][:255] or "accepted"


@sensitive_variables()
def send_to_destination(kind, secret, part):
    """Default sender: webhook for chat services, Web Push for browsers."""
    if kind == Destination.Kind.WEBPUSH:
        return send_web_push(secret, part)
    return send_webhook_part(kind, secret, part)
