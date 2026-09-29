from datetime import UTC, datetime, time
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import collect_for_user
from accounts.tests.helpers import make_rule
from accounts.courses import CourseSyncError
from accounts.models import CanvasConnection, CourseSelection, Destination, NotificationRule
from accounts.notifications import render_notification
from accounts.scheduling import claim_due_runs
from accounts.services import encrypt_secret, verify_and_store_connection
from accounts.tests.test_collection import FakeCanvasClient
from learningx_alert.models import CanvasProfile


KEY = Fernet.generate_key().decode()
NOW = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)  # 09:00 KST


def http_error(code):
    return HTTPError("https://canvas.skku.edu/api/v1/users/self/profile", code, "x", Message(), None)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class ReconnectRequiredTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        for user in (self.user, self.other):
            CanvasConnection.objects.create(
                user=user,
                canvas_user_id=str(user.pk),
                canvas_name="Pilot",
                encrypted_token=encrypt_secret("token"),
                verified_at=timezone.now(),
            )
            make_rule(user, time(9, 0))
            CourseSelection.objects.create(
                user=user,
                canvas_course_id=100 + user.pk,
                course_name="과목",
                enabled=True,
                include_assignments=True,
            )
            Destination.objects.create(
                user=user,
                kind=Destination.Kind.DISCORD,
                encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/x"),
            )
        self.canvas = FakeCanvasClient("unused", "unused")

    def collect(self, user=None):
        return collect_for_user(
            user or self.user, NOW, client_class=lambda _base, _token: self.canvas
        )

    def test_rejected_token_marks_connection_and_reports_once(self):
        self.canvas.profile_error = http_error(401)

        result = self.collect()

        self.assertEqual(result.items, ())
        self.assertEqual([o.error_code for o in result.outcomes], ["canvas_reconnect_required"])
        self.assertEqual(self.canvas.requested_course_ids, [])
        self.assertTrue(CanvasConnection.objects.get(user=self.user).needs_reconnect)
        self.assertFalse(CanvasConnection.objects.get(user=self.other).needs_reconnect)
        self.assertIn("Canvas를 다시 연결해 주세요", render_notification(result, NOW))

    def test_flagged_connection_skips_canvas_entirely(self):
        CanvasConnection.objects.filter(user=self.user).update(needs_reconnect=True)
        self.canvas.profile_error = AssertionError("Canvas must not be called")

        result = self.collect()

        self.assertEqual(result.outcomes[0].error_code, "canvas_reconnect_required")

    def test_non_auth_failures_do_not_flag_reconnect(self):
        for error in (http_error(500), http_error(403), URLError("down"), TimeoutError()):
            with self.subTest(error=error):
                self.canvas.profile_error = error

                result = self.collect()

                self.assertNotIn("canvas_reconnect_required", [o.error_code for o in result.outcomes])
                self.assertFalse(CanvasConnection.objects.get(user=self.user).needs_reconnect)

    def test_scheduler_skips_only_users_needing_reconnect(self):
        CanvasConnection.objects.filter(user=self.user).update(needs_reconnect=True)

        claimed = claim_due_runs(NOW)

        self.assertEqual([run.user_id for run in claimed], [self.other.pk])

    def test_reconnecting_clears_the_flag(self):
        CanvasConnection.objects.filter(user=self.user).update(needs_reconnect=True)

        class Client:
            def __init__(self, _base, _token):
                pass

            def profile(self):
                return CanvasProfile(1, "Pilot")

        verify_and_store_connection(user=self.user, token="new-token", client_class=Client)

        self.assertFalse(CanvasConnection.objects.get(user=self.user).needs_reconnect)

    def test_dashboard_shows_reconnect_notice_and_no_next_run(self):
        CanvasConnection.objects.filter(user=self.user).update(needs_reconnect=True)
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Canvas를 다시 연결해 주세요.")
        self.assertContains(response, "재연결 필요")
        self.assertIsNone(response.context["next_run"])

    def test_dashboard_without_flag_has_no_notice(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Canvas를 다시 연결해 주세요.")


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class ConnectAutoSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)

    def fake_verify(self, *, user, token):
        return CanvasConnection.objects.create(
            user=user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token=encrypt_secret(token),
            verified_at=timezone.now(),
        )

    def test_successful_connect_syncs_courses(self):
        def fake_sync(user):
            CourseSelection.objects.create(user=user, canvas_course_id=1, course_name="A")
            CourseSelection.objects.create(user=user, canvas_course_id=2, course_name="B")
            return CourseSelection.objects.filter(user=user)

        with patch("accounts.views.verify_and_store_connection", side_effect=self.fake_verify), \
                patch("accounts.views.sync_courses", side_effect=fake_sync) as sync:
            response = self.client.post(reverse("canvas_connect"), {"token": "t"}, follow=True)

        sync.assert_called_once_with(self.user)
        self.assertContains(response, "수강 과목 2개를 불러왔어요.")

    def test_sync_failure_keeps_connection_and_warns(self):
        with patch("accounts.views.verify_and_store_connection", side_effect=self.fake_verify), \
                patch("accounts.views.sync_courses", side_effect=CourseSyncError("course_sync_failed")):
            response = self.client.post(reverse("canvas_connect"), {"token": "t"}, follow=True)

        self.assertTrue(CanvasConnection.objects.filter(user=self.user).exists())
        self.assertContains(response, "Canvas를 연결했어요.")
        self.assertContains(response, "과목은 불러오지 못했어요.")

    def test_failed_verification_does_not_sync(self):
        from accounts.services import CanvasConnectionError

        with patch("accounts.views.verify_and_store_connection", side_effect=CanvasConnectionError("x")), \
                patch("accounts.views.sync_courses") as sync:
            self.client.post(reverse("canvas_connect"), {"token": "t"})

        sync.assert_not_called()
