from datetime import time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CanvasConnection,
    CourseSelection,
    Destination,
    NotificationRule,
)
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class NotificationPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="김학재",
            encrypted_token=encrypt_secret("canvas-secret"),
            verified_at=timezone.now(),
        )
        self.course = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="전자회로",
            enabled=True,
            include_assignments=True,
        )
        self.rule = NotificationRule.objects.create(
            user=self.user,
            lookahead_days=3,
            first_time=time(9, 0),
        )
        self.other_rule = NotificationRule.objects.create(
            user=self.other,
            lookahead_days=5,
            first_time=time(10, 0),
        )
        self.webhook_url = "https://discord.com/api/webhooks/123/stored-secret"
        self.destination = Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(self.webhook_url),
        )
        self.client.force_login(self.user)

    def rule_data(self, **overrides):
        data = {
            "lookahead_days": "3",
            "first_time": "09:00",
            "second_time": "",
        }
        data.update(overrides)
        return data

    @patch("accounts.views.sync_courses")
    def test_pages_show_truthful_configuration_scope_without_secrets(self, sync):
        sync.return_value = CourseSelection.objects.filter(user=self.user)

        dashboard = self.client.get(reverse("dashboard"))
        courses = self.client.get(reverse("course_settings"))
        notifications = self.client.get(reverse("notification_settings"))

        self.assertContains(dashboard, "과목 선택")
        self.assertContains(dashboard, "알림 설정")
        self.assertNotContains(dashboard, "자동 알림 실행 중")
        self.assertContains(courses, "과제")
        self.assertContains(courses, "검증 후 제공", count=2)
        self.assertContains(notifications, "마감 조회 범위")
        self.assertContains(notifications, "시험 알림 보내기")
        self.assertContains(
            notifications,
            "웹훅은 저장만으로 전송되지 않습니다",
        )
        for response in (dashboard, courses, notifications):
            self.assertNotContains(response, self.webhook_url)
            self.assertNotContains(response, self.destination.encrypted_webhook_url)

    @patch("accounts.views.sync_courses")
    def test_forms_have_labels_and_disabled_controls_explain_why(self, sync):
        sync.return_value = CourseSelection.objects.filter(user=self.user)

        courses = self.client.get(reverse("course_settings"))
        notifications = self.client.get(reverse("notification_settings"))

        self.assertContains(courses, f'for="id_form-0-enabled"')
        self.assertContains(courses, f'for="id_form-0-include_assignments"')
        self.assertContains(courses, "강의/출석 — 검증 후 제공")
        self.assertContains(courses, "필수 학습자료 — 검증 후 제공")
        self.assertContains(courses, 'type="checkbox" disabled', count=2)
        for field_name in (
            "lookahead_days",
            "first_time",
            "second_time",
            "kind",
            "webhook_url",
        ):
            self.assertContains(notifications, f'for="id_{field_name}"')
            self.assertContains(notifications, f'id="id_{field_name}"')
        self.assertContains(notifications, 'type="number"')
        self.assertContains(notifications, 'min="1"')
        self.assertContains(notifications, 'max="14"')
        self.assertContains(notifications, 'type="time"', count=2)
        self.assertContains(notifications, 'type="password"')

    def test_notification_settings_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("notification_settings"))

        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("notification_settings")}',
        )

    def test_notification_settings_get_does_not_create_default_rule(self):
        self.rule.delete()

        response = self.client.get(reverse("notification_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(NotificationRule.objects.filter(user=self.user).exists())

    def test_lookahead_out_of_range_returns_korean_error_and_preserves_rule(self):
        for value, message in (("0", "1일 이상"), ("15", "14일 이하")):
            with self.subTest(value=value):
                response = self.client.post(
                    reverse("notification_rule_save"),
                    self.rule_data(lookahead_days=value),
                )

                self.assertEqual(response.status_code, 400)
                self.assertContains(response, message, status_code=400)
                self.rule.refresh_from_db()
                self.assertEqual(self.rule.lookahead_days, 3)

    def test_equal_times_return_korean_error_and_preserve_rule(self):
        response = self.client.post(
            reverse("notification_rule_save"),
            self.rule_data(first_time="09:00", second_time="09:00"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "첫 번째 알림 시간과 다른 시간을 선택해 주세요.",
            status_code=400,
        )
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.first_time, time(9, 0))
        self.assertIsNone(self.rule.second_time)

    def test_valid_one_and_two_time_rules_update_only_current_user(self):
        response = self.client.post(
            reverse("notification_rule_save"),
            self.rule_data(lookahead_days="7", first_time="08:30"),
        )

        self.assertRedirects(
            response,
            reverse("notification_settings"),
            fetch_redirect_response=False,
        )
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.lookahead_days, 7)
        self.assertEqual(self.rule.first_time, time(8, 30))
        self.assertIsNone(self.rule.second_time)

        response = self.client.post(
            reverse("notification_rule_save"),
            self.rule_data(
                lookahead_days="7",
                first_time="08:30",
                second_time="18:00",
            ),
        )

        self.assertRedirects(
            response,
            reverse("notification_settings"),
            fetch_redirect_response=False,
        )
        self.rule.refresh_from_db()
        self.other_rule.refresh_from_db()
        self.assertEqual(self.rule.second_time, time(18, 0))
        self.assertEqual(self.other_rule.lookahead_days, 5)
        self.assertEqual(self.other_rule.first_time, time(10, 0))

    def test_valid_post_creates_rule_for_current_user_only(self):
        self.rule.delete()

        response = self.client.post(
            reverse("notification_rule_save"),
            self.rule_data(lookahead_days="4", first_time="07:15"),
        )

        self.assertRedirects(
            response,
            reverse("notification_settings"),
            fetch_redirect_response=False,
        )
        created = NotificationRule.objects.get(user=self.user)
        self.assertEqual(created.lookahead_days, 4)
        self.assertEqual(created.first_time, time(7, 15))
        self.other_rule.refresh_from_db()
        self.assertEqual(self.other_rule.lookahead_days, 5)
