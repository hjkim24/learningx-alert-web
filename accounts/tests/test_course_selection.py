from urllib.error import URLError
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.courses import CourseSyncError, sync_courses
from accounts.models import CanvasConnection, CourseSelection
from accounts.services import encrypt_secret
from learningx_alert.models import Course


KEY = Fernet.generate_key().decode()


class FakeCanvasClient:
    courses_result = []

    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def courses(self):
        return self.courses_result


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class CourseSelectionTests(TestCase):
    def setUp(self):
        FakeCanvasClient.courses_result = []
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        for index, user in enumerate((self.user, self.other), start=1):
            CanvasConnection.objects.create(
                user=user,
                canvas_user_id=str(index),
                canvas_name=f"Canvas {index}",
                encrypted_token=encrypt_secret(f"token-{index}"),
                verified_at=timezone.now(),
            )

    def form_data(self, course, **overrides):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(course.pk),
            "form-0-enabled": "on",
            "form-0-include_assignments": "on",
        }
        data.update(overrides)
        return data

    def test_sync_adds_active_courses_unselected_and_preserves_existing_flags(self):
        existing = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="이전 이름",
            enabled=True,
            include_assignments=True,
        )
        FakeCanvasClient.courses_result = [Course(1, "새 이름"), Course(2, "신규 과목")]

        courses = sync_courses(self.user, client_class=FakeCanvasClient)

        existing.refresh_from_db()
        new_course = CourseSelection.objects.get(user=self.user, canvas_course_id=2)
        self.assertEqual(existing.course_name, "새 이름")
        self.assertTrue(existing.enabled)
        self.assertTrue(existing.include_assignments)
        self.assertFalse(new_course.enabled)
        self.assertFalse(new_course.include_assignments)
        self.assertEqual(
            list(courses.order_by("canvas_course_id").values_list("canvas_course_id", flat=True)),
            [1, 2],
        )

    def test_successful_sync_removes_only_current_users_inactive_courses(self):
        stale = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="지난 과목",
        )
        other = CourseSelection.objects.create(
            user=self.other,
            canvas_course_id=1,
            course_name="타인의 과목",
        )

        sync_courses(self.user, client_class=FakeCanvasClient)

        self.assertFalse(CourseSelection.objects.filter(pk=stale.pk).exists())
        self.assertTrue(CourseSelection.objects.filter(pk=other.pk).exists())

    def test_failed_sync_does_not_delete_existing_courses(self):
        existing = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="보존",
        )
        with patch.object(
            FakeCanvasClient,
            "courses",
            side_effect=URLError("secret upstream"),
        ):
            with self.assertRaises(CourseSyncError):
                sync_courses(self.user, client_class=FakeCanvasClient)

        self.assertTrue(CourseSelection.objects.filter(pk=existing.pk).exists())

    def test_course_settings_requires_login(self):
        response = self.client.get(reverse("course_settings"))

        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("course_settings")}',
        )

    @patch("accounts.views.sync_courses")
    def test_course_settings_scopes_rendered_courses_to_current_user(self, sync):
        own = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="내 과목",
        )
        CourseSelection.objects.create(
            user=self.other,
            canvas_course_id=2,
            course_name="타인 과목",
        )
        sync.return_value = CourseSelection.objects.filter(user=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("course_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own.course_name)
        self.assertNotContains(response, "타인 과목")
        sync.assert_not_called()

    @patch("accounts.views.sync_courses")
    def test_explicit_sync_posts_once(self, sync):
        self.client.force_login(self.user)

        response = self.client.post(reverse("course_sync"))

        sync.assert_called_once_with(self.user)
        self.assertRedirects(
            response,
            reverse("course_settings"),
            fetch_redirect_response=False,
        )

    def test_sync_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse("course_sync"))

        self.assertEqual(response.status_code, 403)

    def test_save_updates_only_current_users_known_course_ids(self):
        own = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="내 과목",
        )
        other = CourseSelection.objects.create(
            user=self.other,
            canvas_course_id=2,
            course_name="타인 과목",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("course_settings_save"),
            self.form_data(own),
        )

        own.refresh_from_db()
        other.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("course_settings"),
            fetch_redirect_response=False,
        )
        self.assertTrue(own.enabled and own.include_assignments)
        self.assertFalse(other.enabled or other.include_assignments)

    def test_forged_other_user_form_id_is_rejected(self):
        other = CourseSelection.objects.create(
            user=self.other,
            canvas_course_id=2,
            course_name="타인 과목",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("course_settings_save"),
            self.form_data(other),
        )

        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertFalse(other.enabled)

    def test_save_rejects_get(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("course_settings_save")).status_code, 405)

    def test_save_requires_csrf_token(self):
        own = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="내 과목",
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse("course_settings_save"), self.form_data(own))

        self.assertEqual(response.status_code, 403)
        own.refresh_from_db()
        self.assertFalse(own.enabled)

    def test_turning_off_every_item_disables_course(self):
        own = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="내 과목",
            enabled=True,
            include_assignments=True,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("course_settings_save"),
            self.form_data(own, **{"form-0-include_assignments": ""}),
        )

        self.assertRedirects(response, reverse("course_settings"))
        own.refresh_from_db()
        self.assertFalse(own.enabled)
        self.assertFalse(own.include_assignments)

    def test_assignment_toggle_alone_enables_course(self):
        own = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="내 과목",
        )
        self.client.force_login(self.user)
        data = self.form_data(own)
        del data["form-0-enabled"]

        response = self.client.post(reverse("course_settings_save"), data)

        self.assertRedirects(response, reverse("course_settings"))
        own.refresh_from_db()
        self.assertTrue(own.enabled)
        self.assertTrue(own.include_assignments)
