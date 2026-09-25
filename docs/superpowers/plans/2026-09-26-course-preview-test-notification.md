# Course Preview and Test Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authenticated pilot user discover their active Canvas courses, opt into assignment alerts, preview incomplete upcoming assignments, save one encrypted Discord or Slack webhook, and send a notification only by pressing the explicit test button.

**Architecture:** Extend the existing `accounts` Django app with user-owned course/rule/destination rows. Reuse the encrypted-secret helpers and the existing SSRF-protected Canvas/network clients. Keep collection and provider delivery as small pure/service modules so the scheduler plan can consume the same typed results without duplicating rules.

**Tech Stack:** Python 3.12, Django 5.2 LTS, SQLite, Django templates/forms, `urllib.request`, `cryptography` Fernet, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-25-learningx-alert-web-design.md`

## Global Constraints

- Work on the visible `feat/course-notifications-scheduler` branch in `/Users/hjkim24/Desktop/learningx-alert-web`; do not use a hidden worktree.
- Keep Django secrets, Google credentials, Fernet keys, Canvas tokens, and webhook URLs out of Git, logs, exceptions, rendered HTML, and test output.
- Keep `CANVAS_BASE_URL` operator-controlled; never accept a Canvas origin from a browser.
- Every state-changing browser action is authenticated, POST-only, CSRF-protected, and filtered by `request.user`.
- Saving a webhook performs validation only; it must never send a request.
- A test notification is sent only by the user's explicit POST to the test endpoint.
- Use `now < due_at <= now + lookahead`; the exact upper boundary is included and already-due items are excluded.
- Default every discovered course and item type to unselected.
- Account A verified Canvas assignments and submission state only. Keep LearningX lecture/attendance and required-material controls visibly disabled until the feasibility gate is rerun successfully; do not claim those types work.
- Use provider-specific allowlists: `discord.com/api/webhooks/<id>/<token>` and `hooks.slack.com/services/<team>/<hook>/<token>`; reject other schemes, hosts, ports, credentials, query strings, fragments, redirects, and non-public DNS results.
- Never auto-retry a webhook after an ambiguous network result.
- Preserve the existing 49 Django tests and 25 feasibility tests.

## Review Focus

- A forged course form ID or another user's course ID must not alter another user's selection; Task 2 tests queryset scoping and cross-user isolation.
- A syntactically plausible webhook resolving to a private address, carrying a query/fragment, or using the wrong provider host must be rejected before any request; Task 4 exercises each class.
- Updating a destination with a blank webhook keeps the existing ciphertext only when the provider is unchanged; Task 4 tests blank-create, blank-same-provider, and provider-change behavior.
- Assignment-list failure and submission-state failure must remain distinguishable from a genuine empty preview; Task 3 asserts structured per-course outcomes.
- Tokens and webhook URLs must remain absent from DEBUG exception pages, messages, and rendered forms; Tasks 3 and 4 use sentinel secrets and response assertions.

---

### Task 1: Add user-owned course, rule, and destination models

**Files:**
- Modify: `accounts/models.py`
- Create: `accounts/migrations/0002_courseselection_notificationrule_destination.py`
- Create: `accounts/tests/test_notification_models.py`

**Interfaces:**
- Consumes: Django user model and existing user cascade behavior.
- Produces: `CourseSelection`, `NotificationRule`, and `Destination` models used by every later task; `Destination.Kind` and `Destination.Status` choices.

- [ ] **Step 1: Write the failing model tests**

Create `accounts/tests/test_notification_models.py`:

```python
from datetime import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import CourseSelection, Destination, NotificationRule


class NotificationModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")

    def test_new_course_types_are_all_opt_in(self):
        course = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="회로이론",
        )
        self.assertFalse(course.enabled)
        self.assertFalse(course.include_assignments)
        self.assertFalse(course.include_lectures)
        self.assertFalse(course.include_required_materials)

    def test_course_identity_is_unique_per_user(self):
        CourseSelection.objects.create(user=self.user, canvas_course_id=101, course_name="A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseSelection.objects.create(user=self.user, canvas_course_id=101, course_name="B")

    def test_rule_rejects_equal_daily_times(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            NotificationRule.objects.create(
                user=self.user,
                lookahead_days=3,
                first_time=time(9, 0),
                second_time=time(9, 0),
            )

    def test_deleting_user_cascades_notification_configuration(self):
        CourseSelection.objects.create(user=self.user, canvas_course_id=101, course_name="A")
        NotificationRule.objects.create(user=self.user, first_time=time(9, 0))
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url="ciphertext",
        )
        self.user.delete()
        self.assertFalse(CourseSelection.objects.exists())
        self.assertFalse(NotificationRule.objects.exists())
        self.assertFalse(Destination.objects.exists())
```

- [ ] **Step 2: Run the tests and verify the missing-model failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_notification_models -v 2`

Expected: FAIL with import errors for `CourseSelection`, `NotificationRule`, and `Destination`.

- [ ] **Step 3: Implement the models and migration**

Append to `accounts/models.py`:

```python
from datetime import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import F, Q


class CourseSelection(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_selections",
    )
    canvas_course_id = models.BigIntegerField()
    course_name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=False)
    include_assignments = models.BooleanField(default=False)
    include_lectures = models.BooleanField(default=False)
    include_required_materials = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "canvas_course_id"),
                name="unique_user_canvas_course",
            )
        ]
        ordering = ("course_name", "canvas_course_id")


class NotificationRule(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_rule",
    )
    lookahead_days = models.PositiveSmallIntegerField(
        default=3,
        validators=(MinValueValidator(1), MaxValueValidator(14)),
    )
    first_time = models.TimeField(default=time(9, 0))
    second_time = models.TimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(second_time__isnull=True) | ~Q(first_time=F("second_time")),
                name="notification_times_are_distinct",
            )
        ]


class Destination(models.Model):
    class Kind(models.TextChoices):
        DISCORD = "discord", "Discord"
        SLACK = "slack", "Slack"

    class Status(models.TextChoices):
        UNTESTED = "untested", "시험 전"
        SUCCEEDED = "succeeded", "시험 성공"
        DEFINITELY_FAILED = "definitely_failed", "전송 실패"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="destination",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    encrypted_webhook_url = models.TextField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.UNTESTED,
    )
    last_tested_at = models.DateTimeField(blank=True, null=True)
```

Run: `.venv/bin/python manage.py makemigrations accounts`

Expected: creates `accounts/migrations/0002_courseselection_notificationrule_destination.py` with the three tables and both database constraints.

- [ ] **Step 4: Run the focused and full suites**

Run: `.venv/bin/python manage.py test accounts.tests.test_notification_models -v 2`

Expected: PASS, 4 tests.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS, existing suites remain green.

- [ ] **Step 5: Commit**

```bash
git add accounts/models.py accounts/migrations/0002_courseselection_notificationrule_destination.py accounts/tests/test_notification_models.py
git commit -m "feat: add notification configuration models"
```

### Task 2: Synchronize and save active course selections

**Files:**
- Create: `accounts/courses.py`
- Modify: `accounts/forms.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Create: `accounts/tests/test_course_selection.py`

**Interfaces:**
- Consumes: `CanvasConnection.encrypted_token`, `decrypt_secret(value)`, `CanvasClient.courses()`, and `CourseSelection` from Task 1.
- Produces: `sync_courses(user, client_class=CanvasClient) -> QuerySet[CourseSelection]`, `CourseSelectionForm`, and authenticated routes `course_settings` and `course_settings_save`.

- [ ] **Step 1: Write failing synchronization tests**

Create `accounts/tests/test_course_selection.py` with a generated Fernet key, two users, encrypted `CanvasConnection` fixtures, and this complete fake:

```python
class FakeCanvasClient:
    courses_result = []

    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def courses(self):
        return self.courses_result
```

Add tests:

```python
def test_sync_adds_active_courses_unselected_and_preserves_existing_flags(self):
    existing = CourseSelection.objects.create(
        user=self.user,
        canvas_course_id=1,
        course_name="이전 이름",
        enabled=True,
        include_assignments=True,
    )
    FakeCanvasClient.courses_result = [Course(1, "새 이름"), Course(2, "신규 과목")]

    sync_courses(self.user, client_class=FakeCanvasClient)

    existing.refresh_from_db()
    new_course = CourseSelection.objects.get(user=self.user, canvas_course_id=2)
    self.assertEqual(existing.course_name, "새 이름")
    self.assertTrue(existing.enabled)
    self.assertTrue(existing.include_assignments)
    self.assertFalse(new_course.enabled)
    self.assertFalse(new_course.include_assignments)

def test_failed_sync_does_not_delete_existing_courses(self):
    CourseSelection.objects.create(user=self.user, canvas_course_id=1, course_name="보존")
    FakeCanvasClient.courses = lambda self: (_ for _ in ()).throw(URLError("secret upstream"))
    with self.assertRaises(CourseSyncError):
        sync_courses(self.user, client_class=FakeCanvasClient)
    self.assertTrue(CourseSelection.objects.filter(user=self.user, canvas_course_id=1).exists())
```

Add view tests that log in `self.user`, create a second user's course, and assert:

```python
def test_save_updates_only_current_users_known_course_ids(self):
    own = CourseSelection.objects.create(user=self.user, canvas_course_id=1, course_name="내 과목")
    other = CourseSelection.objects.create(user=self.other, canvas_course_id=2, course_name="타인 과목")
    self.client.force_login(self.user)
    response = self.client.post(
        reverse("course_settings_save"),
        {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(own.pk),
            "form-0-enabled": "on",
            "form-0-include_assignments": "on",
        },
    )
    own.refresh_from_db()
    other.refresh_from_db()
    self.assertRedirects(response, reverse("course_settings"))
    self.assertTrue(own.enabled and own.include_assignments)
    self.assertFalse(other.enabled or other.include_assignments)

def test_forged_other_user_form_id_is_rejected(self):
    other = CourseSelection.objects.create(user=self.other, canvas_course_id=2, course_name="타인 과목")
    self.client.force_login(self.user)
    response = self.client.post(
        reverse("course_settings_save"),
        {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(other.pk),
            "form-0-enabled": "on",
            "form-0-include_assignments": "on",
        },
    )
    self.assertEqual(response.status_code, 400)
    other.refresh_from_db()
    self.assertFalse(other.enabled)
```

- [ ] **Step 2: Run and verify the missing-service and route failures**

Run: `.venv/bin/python manage.py test accounts.tests.test_course_selection -v 2`

Expected: FAIL because `accounts.courses`, `CourseSelectionForm`, and the two routes do not exist.

- [ ] **Step 3: Implement atomic course synchronization**

Create `accounts/courses.py`:

```python
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
    except (HTTPError, URLError, TimeoutError, PaginationError, ValueError, TypeError, KeyError) as error:
        raise CourseSyncError("course_sync_failed") from error

    active_ids = [course.id for course in courses]
    with transaction.atomic():
        for course in courses:
            CourseSelection.objects.update_or_create(
                user=user,
                canvas_course_id=course.id,
                defaults={"course_name": course.name},
            )
        CourseSelection.objects.filter(user=user).exclude(
            canvas_course_id__in=active_ids
        ).delete()
    return CourseSelection.objects.filter(user=user)
```

Catch `CanvasConnection.DoesNotExist` in the view, not in this service, so callers can distinguish “connect Canvas first” from an upstream failure.

- [ ] **Step 4: Implement the scoped model formset and routes**

Add to `accounts/forms.py`:

```python
from django.forms import modelformset_factory

from .models import CourseSelection


class CourseSelectionForm(forms.ModelForm):
    class Meta:
        model = CourseSelection
        fields = ("enabled", "include_assignments")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled") and not cleaned.get("include_assignments"):
            raise forms.ValidationError("알림을 사용할 항목을 하나 이상 선택해 주세요.")
        if not cleaned.get("enabled"):
            cleaned["include_assignments"] = False
        return cleaned


CourseSelectionFormSet = modelformset_factory(
    CourseSelection,
    form=CourseSelectionForm,
    extra=0,
)
```

Add authenticated `course_settings` and POST-only `course_settings_save` views. `course_settings` calls `sync_courses`, catches only safe expected failures, and renders the formset filtered to `request.user`. `course_settings_save` binds the same filtered queryset, returns HTTP 400 with the rendered form on invalid/forged management data, and saves only that queryset.

Add routes:

```python
path("courses/", views.course_settings, name="course_settings"),
path("courses/save/", views.course_settings_save, name="course_settings_save"),
```

- [ ] **Step 5: Verify RED turns GREEN and run all suites**

Run: `.venv/bin/python manage.py test accounts.tests.test_course_selection -v 2`

Expected: PASS, including sync preservation, failed-sync atomicity, POST/login/CSRF checks, and cross-user isolation.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add accounts/courses.py accounts/forms.py accounts/views.py accounts/urls.py accounts/tests/test_course_selection.py
git commit -m "feat: add scoped course selection"
```

### Task 3: Collect and preview incomplete assignments

**Files:**
- Create: `accounts/collection.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Create: `templates/accounts/course_settings.html`
- Create: `templates/accounts/preview.html`
- Create: `accounts/tests/test_collection.py`
- Create: `accounts/tests/test_preview.py`

**Interfaces:**
- Consumes: enabled `CourseSelection` rows, `NotificationRule.lookahead_days`, `CanvasConnection`, `CanvasClient.assignments()`, and `CanvasClient.submission_state()`.
- Produces: immutable `AlertItem`, `CourseOutcome`, and `CollectionResult` values plus `collect_for_user(user, now, client_class=CanvasClient)` and POST route `preview` for Task 4 and the scheduler plan.

- [ ] **Step 1: Write the failing collection tests**

Define fixtures with literal UTC datetimes and a fake client whose assignment and submission payloads are complete enough to match Canvas (`id`, `name`, `due_at`, `is_quiz_assignment`; workflow states). Add tests whose expected values are hand-derived:

```python
def test_collect_includes_exact_upper_boundary_and_excludes_due_now(self):
    now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    self.fake.assignments_by_course[101] = [
        {"id": 1, "name": "due now", "due_at": "2026-09-26T00:00:00Z", "is_quiz_assignment": False},
        {"id": 2, "name": "upper", "due_at": "2026-09-29T00:00:00Z", "is_quiz_assignment": False},
        {"id": 3, "name": "outside", "due_at": "2026-09-29T00:00:01Z", "is_quiz_assignment": False},
    ]
    result = collect_for_user(self.user, now, client_class=self.fake_class)
    self.assertEqual([item.external_id for item in result.items], ["2"])

def test_collect_excludes_submitted_graded_pending_review_and_quizzes(self):
    self.fake.submissions = {1: "submitted", 2: "graded", 3: "pending_review", 4: "unsubmitted"}
    result = collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertEqual([item.external_id for item in result.items], ["4"])

def test_assignment_failure_is_not_reported_as_empty(self):
    self.fake.assignment_errors.add(101)
    result = collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertEqual(result.outcomes[0].status, "failed")
    self.assertEqual(result.outcomes[0].error_code, "assignments_failed")
    self.assertEqual(result.items, ())

def test_assignment_without_deadline_is_reported_but_not_alerted(self):
    self.fake.assignments_by_course[101] = [
        {"id": 1, "name": "기한 없음", "due_at": None, "is_quiz_assignment": False},
    ]
    result = collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertEqual(result.items, ())
    self.assertEqual(result.outcomes[0].status, "empty")
    self.assertEqual(result.outcomes[0].no_deadline_count, 1)

def test_malformed_deadline_is_failed_not_empty(self):
    self.fake.assignments_by_course[101] = [
        {"id": 1, "name": "잘못된 기한", "due_at": "not-a-date", "is_quiz_assignment": False},
    ]
    result = collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertEqual(result.outcomes[0].status, "failed")
    self.assertEqual(result.outcomes[0].error_code, "assignment_due_invalid")

def test_submission_failure_excludes_unknown_item_and_keeps_other_items(self):
    self.fake.submission_errors.add(1)
    result = collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertEqual([item.external_id for item in result.items], ["2"])
    self.assertEqual(result.outcomes[0].status, "failed")
    self.assertEqual(result.outcomes[0].error_code, "submission_state_failed")

def test_collection_reads_only_current_users_enabled_courses(self):
    CourseSelection.objects.create(
        user=self.other,
        canvas_course_id=999,
        course_name="타인 과목",
        enabled=True,
        include_assignments=True,
    )
    collect_for_user(self.user, self.now, client_class=self.fake_class)
    self.assertNotIn(999, self.fake.requested_course_ids)
```

- [ ] **Step 2: Run and verify collection tests fail for the missing module**

Run: `.venv/bin/python manage.py test accounts.tests.test_collection -v 2`

Expected: FAIL because `accounts.collection` does not exist.

- [ ] **Step 3: Implement typed assignment collection**

Create `accounts/collection.py` with:

```python
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
            outcomes.append(CourseOutcome(
                selection.canvas_course_id,
                selection.course_name,
                "failed",
                "assignments_failed",
                "과제 목록을 확인하지 못했습니다.",
            ))
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
            items.append(AlertItem(
                selection.canvas_course_id,
                selection.course_name,
                str(assignment["id"]),
                "assignment",
                str(assignment.get("name") or "제목 확인 필요"),
                due_at,
                state,
            ))

        if submission_failed:
            outcomes.append(CourseOutcome(
                selection.canvas_course_id,
                selection.course_name,
                "failed",
                "submission_state_failed",
                "일부 과제의 제출 상태를 확인하지 못했습니다.",
                no_deadline_count,
            ))
        elif due_failed:
            outcomes.append(CourseOutcome(
                selection.canvas_course_id,
                selection.course_name,
                "failed",
                "assignment_due_invalid",
                "일부 과제의 마감 시간을 확인하지 못했습니다.",
                no_deadline_count,
            ))
        else:
            status = "success" if len(items) > before else "empty"
            outcomes.append(CourseOutcome(
                selection.canvas_course_id,
                selection.course_name,
                status,
                no_deadline_count=no_deadline_count,
            ))
    return CollectionResult(
        tuple(sorted(items, key=lambda item: item.due_at)),
        tuple(outcomes),
    )
```

- [ ] **Step 4: Write and run failing preview route tests**

In `accounts/tests/test_preview.py`, patch `accounts.views.collect_for_user` to return literal `CollectionResult` values. Assert that preview is login-required, rejects GET, is CSRF-protected, shows KST deadlines and failed outcomes distinctly, does not show another user's course, and never renders the connection ciphertext or token sentinel.

Run: `.venv/bin/python manage.py test accounts.tests.test_preview -v 2`

Expected: FAIL because `preview` and `templates/accounts/preview.html` do not exist.

- [ ] **Step 5: Implement preview and course templates**

Add a POST-only `preview` view:

```python
@login_required
@require_POST
def preview(request):
    try:
        result = collect_for_user(request.user, timezone.now())
    except CanvasConnection.DoesNotExist:
        messages.error(request, "먼저 Canvas 계정을 연결해 주세요.")
        return redirect("dashboard")
    return render(request, "accounts/preview.html", {"result": result})
```

Register `path("preview/", views.preview, name="preview")`. Create `course_settings.html` with the scoped formset, management form, assignments checkbox, and disabled controls labeled “검증 후 제공” for lecture/attendance and required materials. Create `preview.html` that renders item title/course/deadline, reports `no_deadline_count` as “마감 없음”, and renders each failed outcome using only `safe_summary` and `error_code`.

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_collection accounts.tests.test_preview -v 2`

Expected: PASS.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/collection.py accounts/views.py accounts/urls.py templates/accounts/course_settings.html templates/accounts/preview.html accounts/tests/test_collection.py accounts/tests/test_preview.py
git commit -m "feat: preview incomplete Canvas assignments"
```

### Task 4: Save encrypted destinations and send explicit test notifications

**Files:**
- Create: `accounts/notifications.py`
- Modify: `accounts/forms.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Create: `accounts/tests/test_notifications.py`
- Create: `accounts/tests/test_destination_views.py`

**Interfaces:**
- Consumes: `Destination`, `encrypt_secret`, `decrypt_secret`, `validate_https_url`, and `PinnedHTTPSHandler`.
- Produces: `validate_webhook_url(kind, value, resolve_public=True)`, `render_notification(result, now) -> str`, `split_message(text)`, `send_webhook_part(kind, webhook_url, text, opener=None, resolve_public=True) -> str`, `save_destination(user, kind, webhook_url)`, `DestinationForm`, and POST routes `destination_save`, `destination_delete`, and `destination_test`.

- [ ] **Step 1: Write failing provider-boundary tests**

In `accounts/tests/test_notifications.py`, use the existing `FakeOpener`/`FakeResponse` style and patch DNS only at `learningx_alert.network.socket.getaddrinfo`. Add tests for:

```python
def test_discord_requires_exact_host_path_and_no_user_query(self):
    valid = "https://discord.com/api/webhooks/123/abc_DEF-9"
    self.assertEqual(validate_webhook_url("discord", valid, resolve_public=False), valid)
    for invalid in (
        "http://discord.com/api/webhooks/123/token",
        "https://evil.example/api/webhooks/123/token",
        "https://discord.com:8443/api/webhooks/123/token",
        "https://discord.com/api/webhooks/123/token?wait=true",
        "https://discord.com/api/webhooks/123/token#fragment",
    ):
        with self.subTest(invalid=invalid), self.assertRaises(WebhookValidationError):
            validate_webhook_url("discord", invalid, resolve_public=False)

def test_slack_requires_services_path_on_hooks_host(self):
    valid = "https://hooks.slack.com/services/T1/B2/secret"
    self.assertEqual(validate_webhook_url("slack", valid, resolve_public=False), valid)
    with self.assertRaises(WebhookValidationError):
        validate_webhook_url("slack", "https://slack.com/services/T1/B2/secret", resolve_public=False)

@patch(
    "learningx_alert.network.socket.getaddrinfo",
    return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
    ],
)
def test_private_resolution_is_rejected_before_request(self, _resolver):
    with self.assertRaises(WebhookValidationError):
        validate_webhook_url("slack", "https://hooks.slack.com/services/T/B/S")

def test_discord_success_requires_confirmation_id(self):
    opener = FakeOpener([FakeResponse(
        "https://discord.com/api/webhooks/123/token?wait=true",
        b'{"id":"message-1"}',
    )])
    receipt = send_webhook_part(
        "discord",
        "https://discord.com/api/webhooks/123/token",
        "시험",
        opener=opener,
        resolve_public=False,
    )
    self.assertEqual(receipt, "message-1")
    self.assertEqual(json.loads(opener.requests[0].data)["allowed_mentions"], {"parse": []})

def test_slack_success_requires_200_ok_body(self):
    opener = FakeOpener([FakeResponse(
        "https://hooks.slack.com/services/T/B/S",
        b"ok",
    )])
    self.assertEqual(
        send_webhook_part("slack", "https://hooks.slack.com/services/T/B/S", "시험", opener=opener, resolve_public=False),
        "ok",
    )

def test_renderer_orders_items_and_includes_safe_failures(self):
    result = CollectionResult(
        (
            AlertItem(101, "회로", "2", "assignment", "두 번째", datetime(2026, 9, 28, tzinfo=UTC), "unsubmitted"),
            AlertItem(101, "회로", "1", "assignment", "첫 번째", datetime(2026, 9, 27, tzinfo=UTC), "unsubmitted"),
        ),
        (CourseOutcome(202, "재료", "failed", "assignments_failed", "과제 목록을 확인하지 못했습니다."),),
    )
    text = render_notification(result, datetime(2026, 9, 26, tzinfo=UTC))
    self.assertLess(text.index("첫 번째"), text.index("두 번째"))
    self.assertIn("조회 실패", text)
    self.assertIn("assignments_failed", text)

def test_renderer_neutralizes_provider_mentions_from_external_titles(self):
    result = CollectionResult(
        (AlertItem(101, "회로", "1", "assignment", "@everyone <!channel>", datetime(2026, 9, 27, tzinfo=UTC), "unsubmitted"),),
        (),
    )
    text = render_notification(result, datetime(2026, 9, 26, tzinfo=UTC))
    self.assertNotIn("@everyone", text)
    self.assertNotIn("<!channel>", text)

def test_http_4xx_is_definite_and_timeout_is_ambiguous(self):
    discord_url = "https://discord.com/api/webhooks/123/token"
    with self.assertRaises(DefiniteDeliveryError):
        send_webhook_part(
            "discord",
            discord_url,
            "시험",
            opener=RaisingOpener(HTTPError(discord_url, 404, "Not Found", {}, None)),
            resolve_public=False,
        )
    with self.assertRaises(AmbiguousDeliveryError):
        send_webhook_part(
            "discord",
            discord_url,
            "시험",
            opener=RaisingOpener(TimeoutError("network timeout")),
            resolve_public=False,
        )
```

Define `RaisingOpener` in the test file with an `open()` method that raises the exception passed to its constructor. Import `socket`, `HTTPError`, `UTC`, `datetime`, and the Task 3 collection dataclasses explicitly.

- [ ] **Step 2: Run and verify the missing notification module failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_notifications -v 2`

Expected: FAIL because `accounts.notifications` does not exist.

- [ ] **Step 3: Implement strict validation, splitting, and one-attempt delivery**

Create `accounts/notifications.py`. Use `urlsplit`, full-match regular expressions for each provider path, `validate_https_url` for public-address validation, a no-redirect handler, `ProxyHandler({})`, `PinnedHTTPSHandler`, a 30-second timeout, and the existing maximum-response-size discipline. `split_message` must split at 1,900 UTF-16 code units so every Discord part remains below the official 2,000-character ceiling. Discord appends only its own `wait=true` query and requires a JSON `id`; Slack requires HTTP 200 with body exactly `ok` after whitespace stripping.

Implement `render_notification(result, now)` using `ZoneInfo("Asia/Seoul")`. It sorts `result.items` by `due_at`, renders course/title/type/KST deadline, neutralizes provider mention syntax from external course/title text, and appends only `CourseOutcome.safe_summary` plus `error_code` for failed outcomes. It never accepts or renders credentials, URLs, raw response bodies, or exception strings. After a response, compare `response.geturl()` to the internally constructed request URL; do not re-run the user-input validator against Discord's internally appended `wait=true` query.

Expose these concrete exceptions:

```python
class WebhookValidationError(Exception):
    pass


class DefiniteDeliveryError(Exception):
    pass


class AmbiguousDeliveryError(Exception):
    pass
```

Classify a received non-success HTTP response as definite failure. Classify `URLError`, `TimeoutError`, `ConnectionError`, and an invalid/missing success confirmation after the POST begins as ambiguous. Never retry inside this function.

Implement storage without sending:

```python
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
```

- [ ] **Step 4: Write failing destination view tests**

Add tests in `accounts/tests/test_destination_views.py` that assert:

- create requires a URL, encrypts it, never calls `send_webhook_part`, and never renders it;
- a blank update preserves ciphertext for the same provider;
- changing provider with a blank URL returns a validation error and preserves the old row;
- deletion removes only the current user's destination;
- the test route rejects GET, requires CSRF, and calls delivery only after explicit POST;
- succeeded/definitely-failed/needs-review map to safe Korean status and timestamp without echoing exception text or URL;
- another user's destination and ciphertext never appear.

Run: `.venv/bin/python manage.py test accounts.tests.test_destination_views -v 2`

Expected: FAIL because the form and routes do not exist.

- [ ] **Step 5: Implement forms and explicit destination actions**

Add `DestinationForm` with `kind` and password-style `webhook_url`. Accept the existing destination in `__init__`; enforce the blank-update rules in `clean`. Decorate destination POST views with `@sensitive_post_parameters("webhook_url")`.

`destination_save` calls `save_destination` only for a new URL. A blank same-provider update leaves ciphertext untouched. `destination_test` decrypts only the current user's URL, calls `send_webhook_part` exactly once with a fixed message, updates `Destination.status` and `last_tested_at`, and never includes the URL or raw exception in messages. `destination_delete` filters by `request.user`.

Register:

```python
path("destination/save/", views.destination_save, name="destination_save"),
path("destination/delete/", views.destination_delete, name="destination_delete"),
path("destination/test/", views.destination_test, name="destination_test"),
```

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_notifications accounts.tests.test_destination_views -v 2`

Expected: PASS.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/notifications.py accounts/forms.py accounts/views.py accounts/urls.py accounts/tests/test_notifications.py accounts/tests/test_destination_views.py
git commit -m "feat: add encrypted notification destinations"
```

### Task 5: Complete the configuration UI and operator documentation

**Files:**
- Modify: `accounts/forms.py`
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Modify: `templates/accounts/dashboard.html`
- Modify: `templates/accounts/course_settings.html`
- Create: `templates/accounts/notification_settings.html`
- Modify: `static/app.css`
- Modify: `README.md`
- Modify: `.env.example`
- Create: `accounts/tests/test_notification_pages.py`

**Interfaces:**
- Consumes: all Task 1–4 routes/forms/statuses.
- Produces: `NotificationRuleForm`, authenticated GET route `notification_settings`, POST route `notification_rule_save`, responsive server-rendered dashboard/navigation/settings UI, and documented `LEARNINGX_ALLOWED_HOSTS` placeholder for the later verified LearningX expansion.

- [ ] **Step 1: Write failing page-contract tests**

Create `accounts/tests/test_notification_pages.py` and assert authenticated pages contain:

```python
self.assertContains(response, "과목 선택")
self.assertContains(response, "과제")
self.assertContains(response, "검증 후 제공")
self.assertContains(response, "마감 조회 범위")
self.assertContains(response, "시험 알림 보내기")
self.assertContains(response, "웹훅은 저장만으로 전송되지 않습니다")
self.assertNotContains(response, stored_plaintext_webhook)
```

Also assert every form has an accessible label, disabled LearningX controls carry explanatory text, and the dashboard does not claim that scheduled alerts are already running.

Add behavior tests that POST lookahead `0` and `15`, equal first/second times, and valid one-time/two-time rules. Invalid posts must return HTTP 400 with Korean field errors and preserve the existing rule; valid posts must update only `request.user`.

- [ ] **Step 2: Run and verify the page-contract failures**

Run: `.venv/bin/python manage.py test accounts.tests.test_notification_pages -v 2`

Expected: FAIL because the notification settings page and new dashboard content are absent.

- [ ] **Step 3: Implement the server-rendered screens**

Add `NotificationRuleForm` as a `ModelForm` for `lookahead_days`, `first_time`, and `second_time`. Use native number/time widgets, and reject equal non-empty times in `clean`. Add a `notification_settings` GET view that loads only the current user's safe destination fields (`kind`, `status`, `last_tested_at`) and rule, never ciphertext. Add POST-only `notification_rule_save`, bind it to only `request.user`, assign the user before saving a new rule, and return HTTP 400 with the bound form on validation failure. Register both routes:

```python
path("notifications/", views.notification_settings, name="notification_settings"),
path("notifications/rule/", views.notification_rule_save, name="notification_rule_save"),
```

Render native `<input type="number" min="1" max="14">`, `<input type="time">`, provider radio/select, password webhook input, and separate POST buttons for rule save, destination save, test, and delete. Keep the UI functional without JavaScript.

Update the dashboard status rail to show Google, Canvas, courses, and destination configuration truthfully. Link to course settings, preview, and notification settings. Append CSS for the formset table/list, preview outcome states, settings sections, keyboard focus, mobile stacking, and reduced motion; preserve the current visual language and avoid gradients/card grids.

- [ ] **Step 4: Update safe operator documentation**

Update `README.md` to state the new implemented scope, explain that only Canvas assignments are enabled pending LearningX evidence, document explicit test delivery, and state that comma-separated Fernet keys are newest-first during rotation. Add this non-secret placeholder to `.env.example`:

```text
LEARNINGX_ALLOWED_HOSTS=
```

Do not add webhook examples containing token-shaped values.

- [ ] **Step 5: Run final plan verification**

Run: `.venv/bin/python manage.py test`

Expected: PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: PASS, 25 feasibility tests.

Run: `.venv/bin/python manage.py check && .venv/bin/python manage.py makemigrations --check --dry-run && git diff --check`

Expected: no issues, no missing migrations, and no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add accounts/forms.py accounts/views.py accounts/urls.py templates/accounts/dashboard.html templates/accounts/course_settings.html templates/accounts/notification_settings.html static/app.css README.md .env.example accounts/tests/test_notification_pages.py
git commit -m "feat: finish notification configuration experience"
```

## Self-review record

- Spec coverage: active-course discovery, opt-in assignment selection, preview outcome distinctions, rule configuration, encrypted one-provider destination, and explicit test delivery are assigned to Tasks 1–5. LearningX-only item types remain deliberately disabled because `FEASIBILITY.md` does not verify them.
- Placeholder scan: executable snippets contain no `TODO`, `TBD`, or prose placeholders. The `tuple[AlertItem, ...]` notation is Python's concrete variadic-tuple type syntax.
- Type consistency: Task 3 produces `CollectionResult`; the scheduler plan consumes the same type. Task 4 produces `render_notification`, `split_message`, and `send_webhook_part`; the scheduler plan consumes those unchanged.
- Review Focus: each of the five risks maps to a named test task above.
