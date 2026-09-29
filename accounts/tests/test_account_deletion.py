from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
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


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = self.create_populated_user("pilot@example.com", 101)
        self.other = self.create_populated_user("other@example.com", 202)

    def create_populated_user(self, username, course_id):
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
        NotificationRule.objects.create(user=user)
        Destination.objects.create(
            user=user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url="webhook-ciphertext",
        )
        run = ScheduledRun.objects.create(
            user=user,
            scheduled_for=datetime(2026, 9, 26, 0, 0, tzinfo=UTC),
        )
        CourseRunResult.objects.create(
            run=run,
            canvas_course_id=course_id,
            course_name="전자회로",
            status=CourseRunResult.Status.SUCCESS,
        )
        RunItem.objects.create(
            run=run,
            canvas_course_id=course_id,
            external_id="55",
            item_type="assignment",
            title="HW",
            due_at=datetime(2026, 9, 27, 0, 0, tzinfo=UTC),
            observed_state="unsubmitted",
        )
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key=f"key-{course_id}",
        )
        return user

    def test_account_delete_requires_login_and_post(self):
        response = self.client.post(reverse("account_delete"))
        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("account_delete")}',
        )

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("account_delete")).status_code, 405)

    def test_account_delete_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse("account_delete"))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_dashboard_explains_external_revocation_before_deletion(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("notification_settings"))

        self.assertContains(response, "Canvas에서 토큰을 폐기")
        self.assertContains(response, "Discord 또는 Slack에서 웹훅을 삭제")
        self.assertContains(response, f'action="{reverse("account_delete")}"')

    def test_account_delete_cascades_local_data_logs_out_and_preserves_other_user(self):
        own_run_id = ScheduledRun.objects.get(user=self.user).pk
        other_run_id = ScheduledRun.objects.get(user=self.other).pk
        own_user_id = self.user.pk
        other_user_id = self.other.pk
        self.client.force_login(self.user)

        response = self.client.post(reverse("account_delete"))

        self.assertRedirects(
            response,
            reverse("account_login"),
            fetch_redirect_response=False,
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(get_user_model().objects.filter(pk=own_user_id).exists())
        self.assertFalse(CanvasConnection.objects.filter(user_id=own_user_id).exists())
        self.assertFalse(CourseSelection.objects.filter(user_id=own_user_id).exists())
        self.assertFalse(NotificationRule.objects.filter(user_id=own_user_id).exists())
        self.assertFalse(Destination.objects.filter(user_id=own_user_id).exists())
        self.assertFalse(ScheduledRun.objects.filter(pk=own_run_id).exists())
        self.assertFalse(CourseRunResult.objects.filter(run_id=own_run_id).exists())
        self.assertFalse(RunItem.objects.filter(run_id=own_run_id).exists())
        self.assertFalse(Delivery.objects.filter(run_id=own_run_id).exists())
        self.assertTrue(get_user_model().objects.filter(pk=other_user_id).exists())
        self.assertTrue(ScheduledRun.objects.filter(pk=other_run_id).exists())
