from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Delivery, Destination, ScheduledRun
from accounts.services import encrypt_secret

KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], WEB_PUSH_ENABLED=True)
class PushReliabilityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="push@example.com")
        self.client.force_login(self.user)
        self.now = timezone.now()
        self.keys = 0

    def push(self, label="iOS Safari", created=None):
        destination = Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.WEBPUSH,
            label=label,
            encrypted_webhook_url=encrypt_secret('{"endpoint": "https://push.example/%s"}' % label),
        )
        if created:
            Destination.objects.filter(pk=destination.pk).update(created_at=created)
        return destination

    def delivery(self, destination, status, finished_at, code="", label="iOS Safari"):
        self.keys += 1
        run = ScheduledRun.objects.create(
            user=self.user,
            scheduled_for=finished_at - timedelta(seconds=self.keys),
            status=ScheduledRun.Status.SUCCEEDED,
            finished_at=finished_at,
        )
        return Delivery.objects.create(
            run=run,
            destination=destination,
            destination_kind=Destination.Kind.WEBPUSH,
            destination_label=label,
            part_number=1,
            idempotency_key=f"k{self.keys}",
            status=status,
            safe_error_code=code,
            finished_at=finished_at,
        )

    def test_destination_list_shows_last_scheduled_success(self):
        destination = self.push()
        self.delivery(destination, Delivery.Status.SUCCEEDED, self.now - timedelta(days=2))
        latest = self.now - timedelta(hours=3)
        self.delivery(destination, Delivery.Status.SUCCEEDED, latest)

        response = self.client.get(reverse("destination_settings"))

        local = timezone.localtime(latest)
        self.assertContains(response, f"마지막 예약 알림 {local:%m.%d %H:%M}")
        self.assertNotContains(response, "예약 알림 실패")

    def test_failure_newer_than_the_last_success_is_flagged(self):
        destination = self.push()
        self.delivery(destination, Delivery.Status.SUCCEEDED, self.now - timedelta(days=2))
        failed = self.now - timedelta(hours=1)
        self.delivery(destination, Delivery.Status.DEFINITELY_FAILED, failed, "delivery_definite")

        response = self.client.get(reverse("destination_settings"))

        self.assertContains(response, f"예약 알림 실패 {timezone.localtime(failed):%m.%d %H:%M}")

    def test_old_failure_before_a_success_is_not_flagged(self):
        destination = self.push()
        self.delivery(destination, Delivery.Status.DEFINITELY_FAILED, self.now - timedelta(days=2), "delivery_definite")
        self.delivery(destination, Delivery.Status.SUCCEEDED, self.now - timedelta(hours=1))

        self.assertNotContains(self.client.get(reverse("destination_settings")), "예약 알림 실패")

    def test_destination_without_scheduled_deliveries_says_so(self):
        self.push()
        self.assertContains(self.client.get(reverse("destination_settings")), "예약 알림을 아직 받지 않았어요")

    def test_dashboard_asks_to_resubscribe_after_an_expired_push(self):
        # The scheduler deletes the destination on 410; only the delivery row remains.
        gone_at = self.now - timedelta(hours=2)
        self.delivery(None, Delivery.Status.DEFINITELY_FAILED, gone_at, "push_subscription_gone", label="iOS Safari")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "iOS Safari 푸시가 만료돼서 알림을 받지 못했어요.")

    def test_notice_disappears_once_a_browser_is_registered_again(self):
        self.delivery(None, Delivery.Status.DEFINITELY_FAILED, self.now - timedelta(hours=2), "push_subscription_gone")
        self.push(label="iOS Safari 2", created=self.now - timedelta(minutes=5))

        self.assertNotContains(self.client.get(reverse("dashboard")), "푸시가 만료돼서")

    def test_notice_is_not_shown_for_other_users(self):
        other = get_user_model().objects.create_user(username="other@example.com")
        run = ScheduledRun.objects.create(user=other, scheduled_for=self.now, finished_at=self.now)
        Delivery.objects.create(
            run=run, destination_kind=Destination.Kind.WEBPUSH, part_number=1, idempotency_key="other",
            status=Delivery.Status.DEFINITELY_FAILED, safe_error_code="push_subscription_gone", finished_at=self.now,
        )

        self.assertNotContains(self.client.get(reverse("dashboard")), "푸시가 만료돼서")
