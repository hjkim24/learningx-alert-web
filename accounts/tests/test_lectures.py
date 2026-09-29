from datetime import UTC, datetime
from urllib.error import URLError

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import collect_for_user, lecture_completion
from accounts.forms import CourseSelectionForm
from accounts.models import AlarmTime, CanvasConnection, CourseSelection, NotificationRule
from accounts.notifications import render_notification
from accounts.scheduling import claim_due_runs
from accounts.services import encrypt_secret
from accounts.tests.test_collection import FakeCanvasClient
from learningx_alert.learningx import LearningXSessionError


KEY = Fernet.generate_key().decode()


class FakeLearningX:
    def __init__(self):
        self.items = {}
        self.errors = {}
        self.requested = []

    def modules(self, course_id):
        self.requested.append(course_id)
        if course_id in self.errors:
            raise LearningXSessionError(self.errors[course_id])
        return [{"module_id": 1, "title": "1주차", "module_items": self.items.get(course_id, [])}]


def component(item_id, *, due_at="2026-09-27T00:00:00Z", completed=False, kind="everlec",
              title=None, use_attendance=True, published=True):
    """Module item in the shape LearningX /modules returns."""
    return {
        "module_item_id": f"m-{item_id}",
        "title": title or f"강의 {item_id}",
        "content_type": "attendance_item",
        "completed": completed,
        "published": published,
        "content_data": {
            "item_id": item_id,
            "title": title or f"강의 {item_id}",
            "due_at": due_at,
            "use_attendance": use_attendance,
            "item_content_data": {"content_type": kind},
        },
    }


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
    LEARNINGX_ALLOWED_HOSTS=frozenset({"canvas.skku.edu"}),
)
class LectureCollectionTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token=encrypt_secret("secret-token"),
            verified_at=timezone.now(),
        )
        NotificationRule.objects.create(user=self.user, lookahead_days=3)
        self.selection = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="전자회로",
            enabled=True,
            include_lectures=True,
        )
        self.canvas = FakeCanvasClient("unused", "unused")
        self.learningx = FakeLearningX()

    def collect(self):
        return collect_for_user(
            self.user,
            self.now,
            client_class=lambda _base, _token: self.canvas,
            learningx_factory=lambda _client: self.learningx,
        )

    def test_lecture_only_course_alerts_incomplete_lectures_in_window(self):
        self.learningx.items[101] = [
            component("a"),
            component("done", completed=True),
            component("late", due_at="2026-09-29T00:00:01Z"),
            component("past", due_at="2026-09-25T23:59:00Z"),
            component("edge", due_at="2026-09-29T00:00:00Z"),
        ]

        result = self.collect()

        self.assertEqual([item.external_id for item in result.items], ["a", "edge"])
        self.assertTrue(all(item.item_type == "lecture" for item in result.items))
        self.assertEqual(result.outcomes[0].status, "success")
        # Lecture-only course must not trigger Canvas assignment calls.
        self.assertEqual(self.canvas.requested_course_ids, [])

    def test_only_attendance_items_are_lectures(self):
        assignment = component("x")
        assignment["content_type"] = "assignment"
        assignment["content_data"]["use_attendance"] = None
        self.learningx.items[101] = [
            assignment,
            component("pdf", kind="pdf", use_attendance=False),
            component("movie-no-att", kind="movie", use_attendance=False),
            component("draft", published=False),
            component("v", kind="everlec"),
            component("s", kind="screenlecture"),
            component("m", kind="movie"),
        ]

        result = self.collect()

        self.assertEqual([item.external_id for item in result.items], ["v", "s", "m"])

    def test_ambiguous_completion_fails_closed(self):
        self.learningx.items[101] = [
            component("ok"),
            component("unknown", completed=None),
            component("weird", completed="maybe"),
        ]

        result = self.collect()

        self.assertEqual([item.external_id for item in result.items], ["ok"])
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(result.outcomes[0].error_code, "lecture_completion_unknown")

    def test_missing_identifier_fails_closed(self):
        entry = component("x")
        entry["content_data"]["item_id"] = None
        entry["module_item_id"] = None
        self.learningx.items[101] = [entry]

        result = self.collect()

        self.assertEqual(result.items, ())
        self.assertEqual(result.outcomes[0].error_code, "lecture_completion_unknown")

    def test_course_without_learningx_modules_is_unsupported(self):
        self.learningx.errors[101] = "external_tool_missing"

        result = self.collect()

        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(result.outcomes[0].error_code, "lectures_unsupported")

    def test_malformed_modules_payload_fails(self):
        self.learningx.modules = lambda _course_id: {"not": "a list"}

        result = self.collect()

        self.assertEqual(result.outcomes[0].error_code, "lectures_failed")

    def test_learningx_failure_is_not_empty(self):
        self.learningx.errors[101] = "learningx_token_missing"

        result = self.collect()

        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(result.outcomes[0].error_code, "lectures_failed")
        self.assertNotIn("learningx_token_missing", result.outcomes[0].safe_summary)

    def test_malformed_due_and_no_deadline(self):
        self.learningx.items[101] = [
            component("bad", due_at="not-a-date"),
            component("none", due_at=None),
        ]

        result = self.collect()

        self.assertEqual(result.outcomes[0].error_code, "lecture_due_invalid")
        self.assertEqual(result.outcomes[0].no_deadline_count, 1)

    def test_combined_course_merges_sources_into_one_outcome(self):
        self.selection.include_assignments = True
        self.selection.save()
        self.canvas.assignments_by_course[101] = [
            {"id": 7, "name": "과제 7", "due_at": "2026-09-28T00:00:00Z"}
        ]
        self.learningx.items[101] = [component("a")]

        result = self.collect()

        self.assertEqual(
            [(item.item_type, item.external_id) for item in result.items],
            [("lecture", "a"), ("assignment", "7")],
        )
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0].status, "success")

    def test_assignment_failure_still_keeps_lecture_items(self):
        self.selection.include_assignments = True
        self.selection.save()
        self.canvas.assignment_errors.add(101)
        self.learningx.items[101] = [component("a")]

        result = self.collect()

        self.assertEqual([item.external_id for item in result.items], ["a"])
        self.assertEqual(result.outcomes[0].error_code, "assignments_failed")

    @override_settings(LEARNINGX_ALLOWED_HOSTS=frozenset())
    def test_unconfigured_learningx_reports_failure(self):
        result = collect_for_user(
            self.user,
            self.now,
            client_class=lambda _base, _token: self.canvas,
        )

        self.assertEqual(result.outcomes[0].error_code, "learningx_not_configured")

    def test_learningx_not_launched_when_no_course_wants_lectures(self):
        self.selection.include_lectures = False
        self.selection.include_assignments = True
        self.selection.save()
        calls = []

        collect_for_user(
            self.user,
            self.now,
            client_class=lambda _base, _token: self.canvas,
            learningx_factory=lambda client: calls.append(client),
        )

        self.assertEqual(calls, [])

    def test_lecture_only_user_is_scheduled(self):
        from accounts.models import Destination

        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/x"),
        )
        rule = NotificationRule.objects.get(user=self.user)
        slot = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)  # 09:00 KST
        rule.alarms.all().delete()
        AlarmTime.objects.create(rule=rule, time=datetime(2026, 9, 26, 9, 0).time())

        claimed = claim_due_runs(slot)

        self.assertEqual([run.user_id for run in claimed], [self.user.pk])

    def test_attendance_documents_are_labelled_as_materials(self):
        missing_type = component("x")
        del missing_type["content_data"]["item_content_data"]
        self.learningx.items[101] = [
            component("v", kind="everlec"),
            component("p", kind="pdf", title="3주차 필독"),
            component("f", kind="FILE"),
            component("pdf-no-att", kind="pdf", use_attendance=False),
            missing_type,
        ]

        result = self.collect()

        self.assertEqual(
            [(item.external_id, item.item_type) for item in result.items],
            [("v", "lecture"), ("p", "material"), ("f", "material"), ("x", "lecture")],
        )
        text = render_notification(result, self.now)
        self.assertIn("[학습자료] 전자회로 · 3주차 필독", text)
        self.assertIn("[강의] 전자회로 · 강의 v", text)

    def test_notification_labels_lectures(self):
        self.learningx.items[101] = [component("a", title="3주차 영상")]

        text = render_notification(self.collect(), self.now)

        self.assertIn("[강의] 전자회로 · 3주차 영상", text)

    def test_completion_values(self):
        for value, expected in (
            (True, True), (False, False), (1, True), (0, False),
            ("completed", True), ("incomplete", False), (" TRUE ", True),
            (None, None), (2, None), ("maybe", None), ({}, None),
        ):
            with self.subTest(value=value):
                self.assertEqual(lecture_completion(value), expected)


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    LEARNINGX_ALLOWED_HOSTS=frozenset({"canvas.skku.edu"}),
)
class LectureSelectionFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.course = CourseSelection.objects.create(
            user=self.user, canvas_course_id=1, course_name="과목"
        )

    def test_lecture_only_selection_is_valid(self):
        form = CourseSelectionForm(
            {"enabled": "on", "include_lectures": "on"}, instance=self.course
        )

        self.assertTrue(form.is_valid(), form.errors)
        course = form.save()
        self.assertTrue(course.include_lectures)
        self.assertFalse(course.include_assignments)

    def test_lecture_toggle_alone_enables_course(self):
        form = CourseSelectionForm({"include_lectures": "on"}, instance=self.course)

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved.include_lectures)
        self.assertTrue(saved.enabled)

    def test_turning_off_every_item_disables_course(self):
        self.course.enabled = True
        self.course.include_lectures = True
        self.course.save()
        form = CourseSelectionForm({}, instance=self.course)

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertFalse(saved.enabled)
        self.assertFalse(saved.include_lectures)

    @override_settings(LEARNINGX_ALLOWED_HOSTS=frozenset())
    def test_lectures_cannot_be_enabled_when_unconfigured(self):
        form = CourseSelectionForm(
            {"enabled": "on", "include_assignments": "on", "include_lectures": "on"},
            instance=self.course,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.save().include_lectures)

    def test_course_page_renders_enabled_lecture_checkbox(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch("accounts.views.sync_courses") as sync:
            sync.return_value = CourseSelection.objects.filter(user=self.user)
            response = self.client.get(reverse("course_settings"))

        self.assertContains(response, 'for="id_form-0-include_lectures"')
        self.assertNotContains(response, "강의 — 운영 설정 후 제공")
