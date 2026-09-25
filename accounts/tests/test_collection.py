from datetime import UTC, datetime
from urllib.error import URLError

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.collection import collect_for_user
from accounts.models import CanvasConnection, CourseSelection, NotificationRule
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


class FakeCanvasClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.assignments_by_course = {}
        self.submissions = {}
        self.assignment_errors = set()
        self.submission_errors = set()
        self.requested_course_ids = []

    def assignments(self, course_id):
        self.requested_course_ids.append(course_id)
        if course_id in self.assignment_errors:
            raise URLError("secret assignment failure")
        return self.assignments_by_course.get(course_id, [])

    def submission_state(self, course_id, assignment_id):
        if assignment_id in self.submission_errors:
            raise URLError("secret submission failure")
        return self.submissions.get(assignment_id, "unsubmitted")


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class CollectionTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="김학재",
            encrypted_token=encrypt_secret("secret-token"),
            verified_at=timezone.now(),
        )
        NotificationRule.objects.create(user=self.user, lookahead_days=3)
        CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="전자회로",
            enabled=True,
            include_assignments=True,
        )
        self.fake = FakeCanvasClient("unused", "unused")
        self.fake_class = lambda _base_url, _token: self.fake

    def assignment(self, assignment_id, *, due_at="2026-09-27T00:00:00Z", quiz=False):
        return {
            "id": assignment_id,
            "name": f"과제 {assignment_id}",
            "due_at": due_at,
            "is_quiz_assignment": quiz,
        }

    def test_collect_includes_exact_upper_boundary_and_excludes_due_now(self):
        self.fake.assignments_by_course[101] = [
            self.assignment(1, due_at="2026-09-26T00:00:00Z"),
            self.assignment(2, due_at="2026-09-29T00:00:00Z"),
            self.assignment(3, due_at="2026-09-29T00:00:01Z"),
        ]

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual([item.external_id for item in result.items], ["2"])

    def test_collect_excludes_submitted_graded_pending_review_and_quizzes(self):
        self.fake.assignments_by_course[101] = [
            self.assignment(1),
            self.assignment(2),
            self.assignment(3),
            self.assignment(4),
            self.assignment(5, quiz=True),
        ]
        self.fake.submissions = {
            1: "submitted",
            2: "graded",
            3: "pending_review",
            4: "unsubmitted",
            5: "unsubmitted",
        }

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual([item.external_id for item in result.items], ["4"])

    def test_assignment_failure_is_not_reported_as_empty(self):
        self.fake.assignment_errors.add(101)

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(result.outcomes[0].error_code, "assignments_failed")
        self.assertEqual(result.items, ())

    def test_assignment_without_deadline_is_reported_but_not_alerted(self):
        self.fake.assignments_by_course[101] = [self.assignment(1, due_at=None)]

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual(result.items, ())
        self.assertEqual(result.outcomes[0].status, "empty")
        self.assertEqual(result.outcomes[0].no_deadline_count, 1)

    def test_malformed_deadline_is_failed_not_empty(self):
        self.fake.assignments_by_course[101] = [
            self.assignment(1, due_at="not-a-date")
        ]

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertEqual(result.outcomes[0].error_code, "assignment_due_invalid")

    def test_submission_failure_excludes_unknown_item_and_keeps_other_items(self):
        self.fake.assignments_by_course[101] = [self.assignment(1), self.assignment(2)]
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

    def test_items_are_sorted_by_deadline(self):
        self.fake.assignments_by_course[101] = [
            self.assignment(1, due_at="2026-09-28T00:00:00Z"),
            self.assignment(2, due_at="2026-09-27T00:00:00Z"),
        ]

        result = collect_for_user(self.user, self.now, client_class=self.fake_class)

        self.assertEqual([item.external_id for item in result.items], ["2", "1"])
