from datetime import UTC, datetime, time, timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import (
    CanvasConnection,
    CourseSelection,
    Destination,
    ScheduledRun,
)
from accounts.scheduling import CATCH_UP_MINUTES, claim_due_runs, matching_slot, slot_minutes
from accounts.services import encrypt_secret
from accounts.tests.helpers import make_rule, unsaved_rule


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
        make_rule(user, first_time)
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
        rule = unsaved_rule(time(0, 5))
        now = datetime(2026, 9, 25, 15, 5, 37, tzinfo=UTC)

        self.assertEqual(
            matching_slot(rule, now),
            datetime(2026, 9, 25, 15, 5, tzinfo=UTC),
        )

    def test_nonmatching_minute_does_not_backfill_earlier_slot(self):
        rule = unsaved_rule(time(9, 0))
        now = datetime(2026, 9, 26, 0, 1, tzinfo=UTC)

        self.assertIsNone(matching_slot(rule, now))

    def test_second_time_is_due_on_its_own_minute(self):
        rule = unsaved_rule(time(9, 0), time(20, 0))
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


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class CatchUpTests(TestCase):
    """A scan longer than a minute (or a restart) must not drop alarm minutes."""

    make_user_with_rule_and_course = SchedulingTests.make_user_with_rule_and_course
    make_ready_user = SchedulingTests.make_ready_user

    # 09:00 KST == 00:00 UTC
    SLOT_0900 = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)

    def test_slot_minutes_cover_the_gap_and_are_capped(self):
        now = self.SLOT_0900 + timedelta(minutes=3, seconds=20)

        self.assertEqual(slot_minutes(now), [self.SLOT_0900 + timedelta(minutes=3)])
        self.assertEqual(
            slot_minutes(now, since=self.SLOT_0900),
            [self.SLOT_0900 + timedelta(minutes=m) for m in (1, 2, 3)],
        )
        capped = slot_minutes(now, since=now - timedelta(hours=5))
        self.assertEqual(len(capped), CATCH_UP_MINUTES + 1)

    def test_alarm_in_a_minute_the_previous_scan_ran_past_is_claimed(self):
        user = self.make_ready_user(first_time=time(9, 1))
        # Previous scan started 09:00 and ran until 09:02:30; 09:01 was never scanned.
        now = self.SLOT_0900 + timedelta(minutes=2, seconds=30)

        self.assertEqual(claim_due_runs(now), ())  # old behaviour: current minute only
        with self.assertLogs("accounts.scheduling", level="WARNING") as logs:
            claimed = claim_due_runs(now, since=self.SLOT_0900)

        self.assertEqual([run.user for run in claimed], [user])
        self.assertEqual(claimed[0].scheduled_for, self.SLOT_0900 + timedelta(minutes=1))
        self.assertIn("late slot claimed", logs.output[0])

    def test_looking_back_over_already_claimed_minutes_creates_nothing(self):
        self.make_ready_user(first_time=time(9, 0))
        self.assertEqual(len(claim_due_runs(self.SLOT_0900)), 1)

        again = claim_due_runs(self.SLOT_0900 + timedelta(minutes=5), since=self.SLOT_0900 - timedelta(minutes=10))

        self.assertEqual(again, ())
        self.assertEqual(ScheduledRun.objects.count(), 1)

    def test_alarm_older_than_the_catch_up_window_is_not_replayed(self):
        self.make_ready_user(first_time=time(9, 0))
        now = self.SLOT_0900 + timedelta(minutes=CATCH_UP_MINUTES + 1)

        self.assertEqual(claim_due_runs(now, since=now - timedelta(hours=2)), ())


class WeekdayAlarmTests(TestCase):
    """Alarm-clock semantics: weekday masks, on/off, up to five slots."""

    def test_alarm_only_fires_on_selected_weekdays(self):
        # 2026-09-26 is a Saturday in KST; bit 5 = Saturday.
        saturday_09 = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        weekdays_rule = unsaved_rule(time(9, 0), weekdays=0b0011111)
        weekend_rule = unsaved_rule(time(9, 0), weekdays=0b1100000)

        self.assertIsNone(matching_slot(weekdays_rule, saturday_09))
        self.assertEqual(matching_slot(weekend_rule, saturday_09), saturday_09)

    def test_weekday_uses_seoul_date_not_utc_date(self):
        # 2026-09-27 00:05 KST (Sunday) is still Saturday 15:05 in UTC.
        now = datetime(2026, 9, 26, 15, 5, tzinfo=UTC)
        sunday_only = unsaved_rule(time(0, 5), weekdays=0b1000000)
        saturday_only = unsaved_rule(time(0, 5), weekdays=0b0100000)

        self.assertEqual(matching_slot(sunday_only, now), now)
        self.assertIsNone(matching_slot(saturday_only, now))

    def test_disabled_alarm_never_fires(self):
        rule = unsaved_rule(time(9, 0))
        rule.alarms.all()[0].enabled = False

        self.assertIsNone(matching_slot(rule, datetime(2026, 9, 26, 0, 0, tzinfo=UTC)))

    def test_next_alarm_skips_to_next_selected_weekday(self):
        from accounts.scheduling import SEOUL, next_alarm_at

        # Saturday 10:00 KST; a Monday-only 09:00 alarm is two days away.
        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
        rule = unsaved_rule(time(9, 0), weekdays=0b0000001)

        self.assertEqual(
            next_alarm_at(rule, now),
            datetime(2026, 9, 28, 9, 0, tzinfo=SEOUL),
        )

    def test_next_alarm_picks_earliest_of_several(self):
        from accounts.scheduling import SEOUL, next_alarm_at

        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)  # Sat 10:00 KST
        rule = unsaved_rule(time(8, 0), time(12, 30), time(21, 0))

        self.assertEqual(next_alarm_at(rule, now), datetime(2026, 9, 26, 12, 30, tzinfo=SEOUL))

    def test_next_alarm_is_none_when_everything_is_off(self):
        from accounts.scheduling import next_alarm_at

        rule = unsaved_rule(time(9, 0))
        rule.alarms.all()[0].enabled = False

        self.assertIsNone(next_alarm_at(rule, datetime(2026, 9, 26, 0, 0, tzinfo=UTC)))
