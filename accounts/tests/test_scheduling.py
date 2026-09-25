from datetime import UTC, datetime, time

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import (
    CanvasConnection,
    CourseSelection,
    Destination,
    NotificationRule,
    ScheduledRun,
)
from accounts.scheduling import claim_due_runs, matching_slot
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class SchedulingTests(TestCase):
    def make_user_with_rule_and_course(self, *, first_time=time(9, 0)):
        index = get_user_model().objects.count() + 1
        user = get_user_model().objects.create_user(username=f"pilot-{index}@example.com")
        CanvasConnection.objects.create(
            user=user,
            canvas_user_id=str(index),
            canvas_name=f"Pilot {index}",
            encrypted_token=encrypt_secret(f"token-{index}"),
            verified_at=timezone.now(),
        )
        NotificationRule.objects.create(user=user, first_time=first_time)
        CourseSelection.objects.create(
            user=user,
            canvas_course_id=100 + index,
            course_name=f"Course {index}",
            enabled=True,
            include_assignments=True,
        )
        return user

    def make_ready_user(self, *, first_time=time(9, 0)):
        user = self.make_user_with_rule_and_course(first_time=first_time)
        Destination.objects.create(
            user=user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(
                "https://discord.com/api/webhooks/123/secret"
            ),
        )
        return user

    def test_matching_slot_uses_seoul_local_date_across_utc_midnight(self):
        rule = NotificationRule(first_time=time(0, 5))
        now = datetime(2026, 9, 25, 15, 5, 37, tzinfo=UTC)

        self.assertEqual(
            matching_slot(rule, now),
            datetime(2026, 9, 25, 15, 5, tzinfo=UTC),
        )

    def test_nonmatching_minute_does_not_backfill_earlier_slot(self):
        rule = NotificationRule(first_time=time(9, 0))
        now = datetime(2026, 9, 26, 0, 1, tzinfo=UTC)

        self.assertIsNone(matching_slot(rule, now))

    def test_second_time_is_due_on_its_own_minute(self):
        rule = NotificationRule(first_time=time(9, 0), second_time=time(20, 0))
        now = datetime(2026, 9, 26, 11, 0, 12, tzinfo=UTC)

        self.assertEqual(
            matching_slot(rule, now),
            datetime(2026, 9, 26, 11, 0, tzinfo=UTC),
        )

    def test_repeated_scan_claims_one_run(self):
        self.make_ready_user(first_time=time(9, 0))
        now = datetime(2026, 9, 26, 0, 0, 45, tzinfo=UTC)

        first = claim_due_runs(now)
        second = claim_due_runs(now)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertEqual(ScheduledRun.objects.count(), 1)

    def test_unready_users_are_not_claimed(self):
        user_without_destination = self.make_user_with_rule_and_course()

        self.assertEqual(
            claim_due_runs(datetime(2026, 9, 26, 0, 0, tzinfo=UTC)),
            (),
        )
        self.assertFalse(
            ScheduledRun.objects.filter(user=user_without_destination).exists()
        )
