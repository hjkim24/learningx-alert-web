from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import CanvasClient, PaginationError

from .models import CanvasConnection, CourseSelection, NotificationRule
from .services import decrypt_secret


SUBMITTED_STATES = {"submitted", "graded", "pending_review"}


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


def parse_due_at(value):
    if not value:
        return None
    due_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if due_at.tzinfo is None:
        raise ValueError("due_at must include a timezone")
    return due_at.astimezone(UTC)


@sensitive_variables("token")
def collect_for_user(user, now, client_class=CanvasClient):
    connection = CanvasConnection.objects.get(user=user)
    rule, _ = NotificationRule.objects.get_or_create(user=user)
    selections = CourseSelection.objects.filter(
        user=user,
        enabled=True,
        include_assignments=True,
    )
    token = decrypt_secret(connection.encrypted_token)
    client = client_class(settings.CANVAS_BASE_URL, token)
    upper = now + timedelta(days=rule.lookahead_days)
    items = []
    outcomes = []
    expected_errors = (
        HTTPError,
        URLError,
        TimeoutError,
        PaginationError,
        ValueError,
        TypeError,
        KeyError,
    )

    for selection in selections:
        try:
            assignments = client.assignments(selection.canvas_course_id)
        except expected_errors:
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    "failed",
                    "assignments_failed",
                    "과제 목록을 확인하지 못했습니다.",
                )
            )
            continue

        submission_failed = False
        due_failed = False
        no_deadline_count = 0
        before = len(items)
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
            except expected_errors:
                submission_failed = True
                continue
            if state in SUBMITTED_STATES:
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
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    "failed",
                    "submission_state_failed",
                    "일부 과제의 제출 상태를 확인하지 못했습니다.",
                    no_deadline_count,
                )
            )
        elif due_failed:
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    "failed",
                    "assignment_due_invalid",
                    "일부 과제의 마감 시간을 확인하지 못했습니다.",
                    no_deadline_count,
                )
            )
        else:
            status = "success" if len(items) > before else "empty"
            outcomes.append(
                CourseOutcome(
                    selection.canvas_course_id,
                    selection.course_name,
                    status,
                    no_deadline_count=no_deadline_count,
                )
            )
    return CollectionResult(
        tuple(sorted(items, key=lambda item: item.due_at)),
        tuple(outcomes),
    )
