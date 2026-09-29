from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db.models import Q
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import CanvasClient, PaginationError
from learningx_alert.learningx import LearningXClient, LearningXSessionError
from learningx_alert.network import UnsafeUrlError
from learningx_alert.probe import MATERIAL_TYPES

from .models import CanvasConnection, CourseSelection, ExcludedItem, NotificationRule
from .services import decrypt_secret


SUBMITTED_STATES = {"submitted", "graded", "pending_review"}
COMPLETED_VALUES = {"true", "1", "complete", "completed"}
INCOMPLETE_VALUES = {"false", "0", "incomplete", "not_completed"}
MAX_EXTERNAL_ID_LENGTH = 128

EXPECTED_ERRORS = (
    HTTPError,
    URLError,
    TimeoutError,
    PaginationError,
    UnsafeUrlError,
    ValueError,
    TypeError,
    KeyError,
)


@dataclass(frozen=True)
class AlertItem:
    canvas_course_id: int
    course_name: str
    external_id: str
    item_type: str
    title: str
    due_at: datetime
    observed_state: str


@dataclass(frozen=True)
class CourseOutcome:
    canvas_course_id: int
    course_name: str
    status: str
    error_code: str = ""
    safe_summary: str = ""
    no_deadline_count: int = 0


@dataclass(frozen=True)
class CollectionResult:
    items: tuple[AlertItem, ...]
    outcomes: tuple[CourseOutcome, ...]
    excluded_count: int = 0


def load_exclusions(user):
    return {exclusion.key(): exclusion for exclusion in ExcludedItem.objects.filter(user=user)}


def apply_exclusions(user, items, exclusions=None):
    """Drop muted items; forget mutes whose deadline has since changed.

    Returns (kept_items, excluded_count).
    """
    if exclusions is None:
        exclusions = load_exclusions(user)
    if not exclusions:
        return list(items), 0
    kept = []
    stale = []
    excluded = 0
    for item in items:
        exclusion = exclusions.get((item.canvas_course_id, item.item_type, item.external_id))
        if exclusion is None:
            kept.append(item)
        elif exclusion.due_at == item.due_at:
            excluded += 1
        else:
            # The deadline moved: alert again instead of silently muting it.
            stale.append(exclusion.pk)
            kept.append(item)
    if stale:
        ExcludedItem.objects.filter(pk__in=stale).delete()
    return kept, excluded


@dataclass(frozen=True)
class _SourceResult:
    items: tuple[AlertItem, ...] = ()
    error_code: str = ""
    safe_summary: str = ""
    no_deadline_count: int = 0


def alert_selection_filter(prefix=""):
    """Q for an enabled course with at least one alert type turned on."""
    return Q(**{f"{prefix}enabled": True}) & (
        Q(**{f"{prefix}include_assignments": True})
        | Q(**{f"{prefix}include_lectures": True})
    )


def parse_due_at(value):
    if not value:
        return None
    due_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if due_at.tzinfo is None:
        raise ValueError("due_at must include a timezone")
    return due_at.astimezone(UTC)


def lecture_completion(value):
    """True/False for an explicit completion value, None when it cannot be trusted."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {0: False, 1: True}.get(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in COMPLETED_VALUES:
            return True
        if normalized in INCOMPLETE_VALUES:
            return False
    return None


def _collect_assignments(client, selection, now, upper):
    try:
        assignments = client.assignments(selection.canvas_course_id)
    except EXPECTED_ERRORS:
        return _SourceResult(
            error_code="assignments_failed",
            safe_summary="과제 목록을 확인하지 못했습니다.",
        )

    items = []
    submission_failed = False
    due_failed = False
    no_deadline_count = 0
    for assignment in assignments:
        if assignment.get("is_quiz_assignment"):
            continue
        if not assignment.get("due_at"):
            no_deadline_count += 1
            continue
        try:
            due_at = parse_due_at(assignment.get("due_at"))
        except (TypeError, ValueError):
            due_failed = True
            continue
        if due_at is None or not (now < due_at <= upper):
            continue
        try:
            state = client.submission_state(
                selection.canvas_course_id,
                int(assignment["id"]),
            )
        except EXPECTED_ERRORS:
            submission_failed = True
            continue
        if state in SUBMITTED_STATES:
            continue
        if state != "unsubmitted":
            submission_failed = True
            continue
        items.append(
            AlertItem(
                selection.canvas_course_id,
                selection.course_name,
                str(assignment["id"]),
                "assignment",
                str(assignment.get("name") or "제목 확인 필요"),
                due_at,
                state,
            )
        )

    if submission_failed:
        return _SourceResult(
            tuple(items),
            "submission_state_failed",
            "일부 과제의 제출 상태를 확인하지 못했습니다.",
            no_deadline_count,
        )
    if due_failed:
        return _SourceResult(
            tuple(items),
            "assignment_due_invalid",
            "일부 과제의 마감 시간을 확인하지 못했습니다.",
            no_deadline_count,
        )
    return _SourceResult(tuple(items), no_deadline_count=no_deadline_count)


def _module_items(modules):
    if not isinstance(modules, list):
        raise TypeError("modules must be a list")
    for module in modules:
        if not isinstance(module, dict):
            raise TypeError("module must be an object")
        module_items = module.get("module_items") or []
        if not isinstance(module_items, list):
            raise TypeError("module_items must be a list")
        yield from module_items


def _attendance_item_type(content):
    """'material' for attendance-tracked documents (pdf, file, ...), else 'lecture'."""
    item_content = content.get("item_content_data")
    content_type = item_content.get("content_type") if isinstance(item_content, dict) else ""
    return "material" if str(content_type or "").strip().lower() in MATERIAL_TYPES else "lecture"


def _collect_lectures(learningx, selection, now, upper):
    """Unfinished LearningX attendance lectures from the weekly modules.

    A lecture is a module item whose content requires attendance
    (``content_data.use_attendance is True``); completion comes from the
    item's ``completed`` flag and the deadline from ``content_data.due_at``.
    """
    if learningx is None:
        return _SourceResult(
            error_code="learningx_not_configured",
            safe_summary="강의 알림이 아직 설정되지 않았습니다.",
        )
    try:
        module_items = list(_module_items(learningx.modules(selection.canvas_course_id)))
    except LearningXSessionError as error:
        if str(error) == "external_tool_missing":
            return _SourceResult(
                error_code="lectures_unsupported",
                safe_summary="이 과목에는 LearningX 주차학습이 없습니다.",
            )
        return _SourceResult(
            error_code="lectures_failed",
            safe_summary="강의 목록을 확인하지 못했습니다.",
        )
    except EXPECTED_ERRORS:
        return _SourceResult(
            error_code="lectures_failed",
            safe_summary="강의 목록을 확인하지 못했습니다.",
        )

    items = []
    completion_failed = False
    due_failed = False
    no_deadline_count = 0
    for module_item in module_items:
        if not isinstance(module_item, dict):
            completion_failed = True
            continue
        content = module_item.get("content_data")
        if not isinstance(content, dict) or content.get("use_attendance") is not True:
            continue
        if module_item.get("published") is False or content.get("published") is False:
            continue
        if not content.get("due_at"):
            no_deadline_count += 1
            continue
        try:
            due_at = parse_due_at(content.get("due_at"))
        except (TypeError, ValueError):
            due_failed = True
            continue
        if due_at is None or not (now < due_at <= upper):
            continue
        completed = lecture_completion(module_item.get("completed"))
        external_id = str(
            content.get("item_id") or module_item.get("module_item_id") or ""
        )
        if completed is None or not external_id or len(external_id) > MAX_EXTERNAL_ID_LENGTH:
            # Fail closed: an item we cannot identify or whose completion is
            # ambiguous is neither alerted nor silently treated as done.
            completion_failed = True
            continue
        if completed:
            continue
        items.append(
            AlertItem(
                selection.canvas_course_id,
                selection.course_name,
                external_id,
                _attendance_item_type(content),
                str(module_item.get("title") or content.get("title") or "제목 확인 필요"),
                due_at,
                "incomplete",
            )
        )

    if completion_failed:
        return _SourceResult(
            tuple(items),
            "lecture_completion_unknown",
            "일부 강의의 수강 완료 여부를 확인하지 못했습니다.",
            no_deadline_count,
        )
    if due_failed:
        return _SourceResult(
            tuple(items),
            "lecture_due_invalid",
            "일부 강의의 마감 시간을 확인하지 못했습니다.",
            no_deadline_count,
        )
    return _SourceResult(tuple(items), no_deadline_count=no_deadline_count)


RECONNECT_OUTCOME = CourseOutcome(
    0,
    "Canvas 연결",
    "failed",
    "canvas_reconnect_required",
    "Canvas 토큰이 만료되었거나 철회되었습니다. 사이트에서 Canvas를 다시 연결해 주세요.",
)


def _token_rejected(client):
    """True only when Canvas definitively rejects the token (HTTP 401)."""
    try:
        client.profile()
    except HTTPError as error:
        return error.code == 401
    except EXPECTED_ERRORS:
        # Network trouble is not a token problem; courses report it themselves.
        return False
    return False


def default_learningx_factory(canvas_client):
    if not settings.LEARNINGX_ALLOWED_HOSTS:
        return None
    return LearningXClient(canvas_client, set(settings.LEARNINGX_ALLOWED_HOSTS))


@sensitive_variables("token")
def collect_for_user(
    user,
    now,
    client_class=CanvasClient,
    learningx_factory=default_learningx_factory,
):
    connection = CanvasConnection.objects.get(user=user)
    if connection.needs_reconnect:
        return CollectionResult((), (RECONNECT_OUTCOME,))
    rule, _ = NotificationRule.objects.get_or_create(user=user)
    selections = list(
        CourseSelection.objects.filter(alert_selection_filter(), user=user)
    )
    token = decrypt_secret(connection.encrypted_token)
    client = client_class(settings.CANVAS_BASE_URL, token)
    if _token_rejected(client):
        CanvasConnection.objects.filter(pk=connection.pk).update(needs_reconnect=True)
        return CollectionResult((), (RECONNECT_OUTCOME,))
    learningx = None
    if any(selection.include_lectures for selection in selections):
        learningx = learningx_factory(client)
    upper = now + timedelta(days=rule.lookahead_days)
    items = []
    outcomes = []
    excluded_total = 0
    exclusions = load_exclusions(user)

    for selection in selections:
        sources = []
        if selection.include_assignments:
            sources.append(_collect_assignments(client, selection, now, upper))
        if selection.include_lectures:
            sources.append(_collect_lectures(learningx, selection, now, upper))

        course_items = [item for source in sources for item in source.items]
        course_items, course_excluded = apply_exclusions(user, course_items, exclusions)
        excluded_total += course_excluded
        items.extend(course_items)
        no_deadline_count = sum(source.no_deadline_count for source in sources)
        failure = next((source for source in sources if source.error_code), None)
        if failure:
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    "failed",
                    failure.error_code,
                    failure.safe_summary,
                    no_deadline_count,
                )
            )
        else:
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    "success" if course_items else "empty",
                    no_deadline_count=no_deadline_count,
                )
            )
    return CollectionResult(
        tuple(sorted(items, key=lambda item: item.due_at)),
        tuple(outcomes),
        excluded_total,
    )
