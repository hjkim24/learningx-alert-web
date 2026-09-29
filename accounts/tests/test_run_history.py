from datetime import UTC, datetime, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CanvasConnection,
    CourseRunResult,
    CourseSelection,
    Delivery,
    Destination,
    NotificationRule,
    RunItem,
    ScheduledRun,
)


class RunHistoryTests(TestCase):
    def setUp(self):
        self.user = self.create_ready_user("pilot@example.com", 101)
        self.other = self.create_ready_user("other@example.com", 202)
        self.own_run = self.create_populated_run(
            self.user,
            "내 과제",
            "message-own",
            "ciphertext-sentinel",
        )
        self.other_run = self.create_populated_run(
            self.other,
            "타인 과제",
            "message-other",
            "other-idempotency",
        )

    def create_ready_user(self, username, course_id):
        user = get_user_model().objects.create_user(username=username)
        CanvasConnection.objects.create(
            user=user,
            canvas_user_id=str(course_id),
            canvas_name=username,
            encrypted_token="canvas-ciphertext",
            verified_at=timezone.now(),
        )
        CourseSelection.objects.create(
            user=user,
            canvas_course_id=course_id,
            course_name="전자회로",
            enabled=True,
            include_assignments=True,
        )
        NotificationRule.objects.create(
            user=user,
            first_time=time(9, 0),
            second_time=time(20, 0),
        )
        Destination.objects.create(
            user=user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url="webhook-sentinel",
            status=Destination.Status.NEEDS_REVIEW,
        )
        return user

    def create_populated_run(self, user, title, confirmation, idempotency_key):
        run = ScheduledRun.objects.create(
            user=user,
            scheduled_for=datetime(2026, 9, 26, 0, 0, tzinfo=UTC),
            status=ScheduledRun.Status.NEEDS_REVIEW,
            safe_error_code="delivery_ambiguous",
            started_at=datetime(2026, 9, 26, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 9, 26, 0, 1, tzinfo=UTC),
        )
        CourseRunResult.objects.create(
            run=run,
            canvas_course_id=101,
            course_name="전자회로",
            status=CourseRunResult.Status.FAILED,
            error_code="assignments_failed",
            safe_summary="과제 목록을 확인하지 못했습니다.",
        )
        RunItem.objects.create(
            run=run,
            canvas_course_id=101,
            external_id="55",
            item_type="assignment",
            title=title,
            due_at=datetime(2026, 9, 27, 0, 0, tzinfo=UTC),
            observed_state="unsubmitted",
        )
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key=idempotency_key,
            provider_confirmation_id=confirmation,
            status=Delivery.Status.NEEDS_REVIEW,
            safe_error_code="delivery_ambiguous",
        )
        return run

    def test_run_detail_contains_only_current_users_safe_snapshots(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("run_detail", args=(self.own_run.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "내 과제")
        self.assertContains(response, "assignments_failed")
        self.assertContains(response, "message-own")
        self.assertNotContains(response, "타인 과제")
        self.assertNotContains(response, "ciphertext-sentinel")
        self.assertNotContains(response, "webhook-sentinel")

    def test_other_users_run_is_404(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("run_detail", args=(self.other_run.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_run_detail_requires_login(self):
        run_url = reverse("run_detail", args=(self.own_run.pk,))
        response = self.client.get(run_url)

        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={run_url}',
        )

    @patch(
        "accounts.views.timezone.now",
        return_value=datetime(2026, 9, 26, 1, 0, tzinfo=UTC),
    )
    def test_dashboard_shows_recent_run_and_truthful_next_schedule(self, _now):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "최근 실행")
        self.assertContains(response, "다음 알림")
        self.assertContains(response, "2026.09.26 20:00 KST")
        self.assertContains(response, "assignments_failed")
        self.assertContains(response, reverse("run_detail", args=(self.own_run.pk,)))
        self.assertNotContains(response, reverse("run_detail", args=(self.other_run.pk,)))
        self.assertEqual(ScheduledRun.objects.count(), 2)

    @patch(
        "accounts.views.timezone.now",
        return_value=datetime(2026, 9, 26, 0, 0, 59, tzinfo=UTC),
    )
    def test_dashboard_advances_past_a_started_schedule_minute(self, _now):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "2026.09.26 20:00 KST")

    @patch(
        "accounts.views.timezone.now",
        return_value=datetime(2026, 9, 26, 0, 0, tzinfo=UTC),
    )
    def test_dashboard_advances_past_an_already_claimed_current_slot(self, _now):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "2026.09.26 20:00 KST")

    @patch(
        "accounts.views.timezone.now",
        return_value=datetime(2026, 9, 26, 1, 0, tzinfo=UTC),
    )
    def test_dashboard_requires_an_assignment_enabled_course(self, _now):
        self.user.course_selections.update(include_assignments=False)
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["selected_course_count"], 0)
        self.assertIsNone(response.context["next_run"])
        self.assertContains(
            response,
            "Canvas, 과목, 알림 시간과 대상을 모두 설정하면 표시됩니다.",
        )
