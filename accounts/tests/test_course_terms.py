from datetime import UTC, datetime
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.courses import UNKNOWN_TERM_LABEL, group_forms_by_term, sync_courses
from accounts.forms import CourseSelectionFormSet
from accounts.models import CanvasConnection, CourseSelection
from accounts.services import encrypt_secret
from learningx_alert.models import Course


KEY = Fernet.generate_key().decode()
FALL_2026 = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
SPRING_2026 = datetime(2026, 2, 1, 15, 0, tzinfo=UTC)
SPRING_2027 = datetime(2027, 2, 1, 15, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)


class FakeCanvasClient:
    courses_result = []

    def __init__(self, base_url, token):
        pass

    def courses(self):
        return self.courses_result


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class CourseTermTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token=encrypt_secret("token"),
            verified_at=timezone.now(),
        )

    def course(self, course_id, term_name="", term_start_at=None, **flags):
        return CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=course_id,
            course_name=f"과목 {course_id}",
            term_name=term_name,
            term_start_at=term_start_at,
            **flags,
        )

    def groups(self):
        formset = CourseSelectionFormSet(queryset=CourseSelection.objects.filter(user=self.user))
        return group_forms_by_term(formset.forms, NOW)

    def test_sync_stores_and_updates_term(self):
        FakeCanvasClient.courses_result = [Course(1, "A", "2026년 2학기", FALL_2026)]
        sync_courses(self.user, client_class=FakeCanvasClient)
        course = CourseSelection.objects.get(user=self.user, canvas_course_id=1)
        self.assertEqual((course.term_name, course.term_start_at), ("2026년 2학기", FALL_2026))

        FakeCanvasClient.courses_result = [Course(1, "A")]
        sync_courses(self.user, client_class=FakeCanvasClient)
        course.refresh_from_db()
        self.assertEqual((course.term_name, course.term_start_at), ("", None))

    def test_groups_newest_first_unknown_last_and_current_is_latest_started(self):
        self.course(1, "2026년 1학기", SPRING_2026)
        self.course(2, "2027년 1학기", SPRING_2027)  # published early, not started
        self.course(3)
        self.course(4, "2026년 2학기", FALL_2026)
        self.course(5, "2026년 2학기", FALL_2026)

        groups = self.groups()

        self.assertEqual(
            [group.name for group in groups],
            ["2027년 1학기", "2026년 2학기", "2026년 1학기", UNKNOWN_TERM_LABEL],
        )
        self.assertEqual([len(group.forms) for group in groups], [1, 2, 1, 1])
        self.assertEqual([group.is_current for group in groups], [False, True, False, False])
        self.assertEqual([group.open for group in groups], [False, True, False, False])

    def test_old_term_with_enabled_course_stays_open(self):
        self.course(1, "2026년 2학기", FALL_2026)
        self.course(2, "2021년 1학기", datetime(2021, 1, 24, 15, tzinfo=UTC), enabled=True, include_assignments=True)

        old = self.groups()[1]

        self.assertEqual((old.enabled_count, old.open), (1, True))

    def test_only_unknown_terms_are_open(self):
        self.course(1)

        (group,) = self.groups()

        self.assertTrue(group.open)

    def test_course_page_renders_term_groups_and_keeps_form_indices(self):
        self.course(1, "2021년 1학기", datetime(2021, 1, 24, 15, tzinfo=UTC))
        self.course(2, "2026년 2학기", FALL_2026)
        self.client.force_login(self.user)

        with patch("accounts.views.timezone.now", return_value=NOW):
            response = self.client.get(reverse("course_settings"))

        content = response.content.decode()
        self.assertLess(content.index("2026년 2학기"), content.index("2021년 1학기"))
        self.assertContains(response, "현재 학기")
        self.assertContains(response, '<details class="term-group" open>', count=1)
        self.assertContains(response, 'name="form-0-id"')
        self.assertContains(response, 'name="form-1-id"')

    def test_saving_a_course_in_a_collapsed_term_works(self):
        old = self.course(1, "2021년 1학기", datetime(2021, 1, 24, 15, tzinfo=UTC))
        self.course(2, "2026년 2학기", FALL_2026)
        self.client.force_login(self.user)
        forms = list(CourseSelection.objects.filter(user=self.user))
        data = {
            "form-TOTAL_FORMS": str(len(forms)),
            "form-INITIAL_FORMS": str(len(forms)),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index, course in enumerate(forms):
            data[f"form-{index}-id"] = str(course.pk)
            if course.pk == old.pk:
                data[f"form-{index}-enabled"] = "on"
                data[f"form-{index}-include_assignments"] = "on"

        response = self.client.post(reverse("course_settings_save"), data)

        self.assertEqual(response.status_code, 302)
        old.refresh_from_db()
        self.assertTrue(old.enabled)
