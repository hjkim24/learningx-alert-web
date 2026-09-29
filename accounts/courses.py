import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import CanvasClient, PaginationError

from .models import CanvasConnection, CourseSelection
from .services import decrypt_secret


class CourseSyncError(Exception):
    pass


@sensitive_variables("token")
def sync_courses(user, client_class=CanvasClient):
    connection = CanvasConnection.objects.get(user=user)
    token = decrypt_secret(connection.encrypted_token)
    try:
        courses = client_class(settings.CANVAS_BASE_URL, token).courses()
    except (
        HTTPError,
        URLError,
        TimeoutError,
        PaginationError,
        ValueError,
        TypeError,
        KeyError,
    ) as error:
        raise CourseSyncError("course_sync_failed") from error

    active_ids = [course.id for course in courses]
    with transaction.atomic():
        for course in courses:
            CourseSelection.objects.update_or_create(
                user=user,
                canvas_course_id=course.id,
                defaults={
                    "course_name": course.name[:255],
                    "term_name": (course.term_name or "")[:128],
                    "term_start_at": course.term_start_at,
                },
            )
        CourseSelection.objects.filter(user=user).exclude(
            canvas_course_id__in=active_ids
        ).delete()
    return CourseSelection.objects.filter(user=user)


UNKNOWN_TERM_LABEL = "학기 정보 없음"


@dataclass
class TermGroup:
    name: str
    start_at: object
    forms: list = field(default_factory=list)
    is_current: bool = False
    enabled_count: int = 0
    has_errors: bool = False

    @property
    def open(self):
        return self.is_current or self.enabled_count > 0 or self.has_errors


TERM_YEAR = re.compile(r"(20\d{2})")
# Rank inside one year, later in the list = shown first (sorted descending).
# 비정규 (non-regular) goes to the bottom of its year, below 1학기.
TERM_KIND_RANKS = (
    (re.compile(r"동계|겨울|winter", re.I), 4),
    (re.compile(r"2\s*학기|fall|autumn", re.I), 3),
    (re.compile(r"하계|여름|summer", re.I), 2),
    (re.compile(r"1\s*학기|spring", re.I), 1),
)


def term_sort_key(group):
    """(has_year, year, kind rank, start, name) — sort descending for newest first."""
    epoch = datetime.min.replace(tzinfo=UTC)
    match = TERM_YEAR.search(group.name)
    rank = next((value for pattern, value in TERM_KIND_RANKS if pattern.search(group.name)), 0)
    return (
        match is not None,
        int(match.group(1)) if match else 0,
        rank,
        group.start_at or epoch,
        group.name,
    )


def group_forms_by_term(forms, now):
    """Group course forms by Canvas term, newest term first, unknown term last.

    The current term is the latest one that has already started, so a next
    term published early does not replace the one in progress.
    """
    groups = {}
    for form in forms:
        course = form.instance
        key = (course.term_name, course.term_start_at) if course.term_name else None
        group = groups.get(key)
        if group is None:
            group = groups[key] = TermGroup(
                course.term_name or UNKNOWN_TERM_LABEL,
                course.term_start_at if course.term_name else None,
            )
        group.forms.append(form)
        group.enabled_count += int(course.enabled)
        group.has_errors |= bool(form.errors)

    known = [group for key, group in groups.items() if key is not None]
    started = [group for group in known if group.start_at and group.start_at <= now]
    if started:
        max(started, key=lambda group: group.start_at).is_current = True
    ordered = sorted(known, key=term_sort_key, reverse=True)
    if None in groups:
        ordered.append(groups[None])
    if not started and ordered:
        ordered[0].is_current = True
    return ordered
