from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.collection import CollectionResult, CourseOutcome
from accounts.models import Destination, NotificationRule, ScheduledRun
from accounts.scheduling import execute_run
from accounts.services import encrypt_secret
from accounts.tests.helpers import alarm_post_data, make_rule

KEY = Fernet.generate_key().decode()
EMPTY = CollectionResult((), (CourseOutcome(101, "A", "empty"),))
# 2026-09-26 09:00 and 21:00 KST
MORNING = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
EVENING = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
NEXT_MORNING = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class EmptyNoticeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="quiet@example.com")
        self.rule = make_rule(self.user)
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/secret"),
        )
        self.sent = []

    def sender(self, kind, secret, part):
        self.sent.append(part)
        return "ok"

    def run_at(self, when, result=EMPTY):
        run = ScheduledRun.objects.create(user=self.user, scheduled_for=when)
        execute_run(run, when, collector=lambda user, now: result, sender=self.sender)
        run.refresh_from_db()
        return run

    def turn_on(self):
        NotificationRule.objects.filter(pk=self.rule.pk).update(notify_when_empty=True)

    def test_off_by_default_keeps_the_silent_empty_run(self):
        self.assertFalse(self.rule.notify_when_empty)
        run = self.run_at(MORNING)
        self.assertEqual(run.status, ScheduledRun.Status.EMPTY)
        self.assertEqual(self.sent, [])

    def test_on_sends_the_nothing_due_message_once_per_kst_day(self):
        self.turn_on()

        morning = self.run_at(MORNING)
        evening = self.run_at(EVENING)
        next_day = self.run_at(NEXT_MORNING)

        self.assertEqual(morning.status, ScheduledRun.Status.SUCCEEDED)
        self.assertEqual(evening.status, ScheduledRun.Status.EMPTY)
        self.assertEqual(next_day.status, ScheduledRun.Status.SUCCEEDED)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("마감되는 과제·강의가 없어요", self.sent[0])

    def test_without_destinations_stays_empty_instead_of_failing(self):
        self.turn_on()
        Destination.objects.filter(user=self.user).delete()

        run = self.run_at(MORNING)

        self.assertEqual(run.status, ScheduledRun.Status.EMPTY)
        self.assertEqual(run.safe_error_code, "")

    def test_a_failed_delivery_does_not_use_up_the_day(self):
        self.turn_on()

        def failing(kind, secret, part):
            from accounts.notifications import DefiniteDeliveryError

            raise DefiniteDeliveryError("down")

        run = ScheduledRun.objects.create(user=self.user, scheduled_for=MORNING)
        execute_run(run, MORNING, collector=lambda user, now: EMPTY, sender=failing)

        evening = self.run_at(EVENING)
        self.assertEqual(evening.status, ScheduledRun.Status.SUCCEEDED)
        self.assertEqual(len(self.sent), 1)

    def test_settings_page_saves_the_toggle(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("notification_settings"))
        self.assertContains(page, 'name="notify_when_empty"')
        self.assertContains(page, "알릴 게 없는 날도 알려 주기")
        self.assertContains(page, "그날 처음 비어 있던 알림 시각")

        alarm = self.rule.alarms.get()
        data = {"lookahead_days": "3", "notify_when_empty": "on", **alarm_post_data("09:00", existing=[alarm.pk])}
        response = self.client.post(reverse("notification_settings_save"), data)

        self.assertEqual(response.status_code, 302)
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.notify_when_empty)
