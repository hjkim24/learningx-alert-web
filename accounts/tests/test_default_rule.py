from datetime import UTC, datetime, time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import collect_for_user
from accounts.models import (
    EVERY_DAY,
    AlarmTime,
    CanvasConnection,
    CourseSelection,
    Destination,
    NotificationRule,
    ensure_default_rule,
)
from accounts.scheduling import claim_due_runs
from accounts.services import CanvasConnectionError, encrypt_secret
from accounts.tests.helpers import make_rule
from accounts.tests.test_collection import FakeCanvasClient


KEY = Fernet.generate_key().decode()


def alarms_of(user):
    return list(
        AlarmTime.objects.filter(rule__user=user).values_list("time", "weekdays", "enabled")
    )


class EnsureDefaultRuleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="new@example.com")

    def test_new_user_gets_three_days_and_daily_nine_am(self):
        rule = ensure_default_rule(self.user)

        self.assertEqual(rule.lookahead_days, 3)
        self.assertEqual(alarms_of(self.user), [(time(9, 0), EVERY_DAY, True)])

    def test_is_idempotent(self):
        ensure_default_rule(self.user)
        ensure_default_rule(self.user)

        self.assertEqual(NotificationRule.objects.filter(user=self.user).count(), 1)
        self.assertEqual(AlarmTime.objects.filter(rule__user=self.user).count(), 1)

    def test_existing_schedule_is_left_alone(self):
        make_rule(self.user, time(7, 30), lookahead_days=7, weekdays=0b0011111)

        rule = ensure_default_rule(self.user)

        self.assertEqual(rule.lookahead_days, 7)
        self.assertEqual(alarms_of(self.user), [(time(7, 30), 0b0011111, True)])

    def test_alarms_switched_off_by_the_user_stay_off(self):
        rule = make_rule(self.user, time(9, 0))
        rule.alarms.update(enabled=False)

        ensure_default_rule(self.user)

        self.assertEqual(alarms_of(self.user), [(time(9, 0), EVERY_DAY, False)])

    def test_rule_without_alarms_gets_the_default_alarm(self):
        NotificationRule.objects.create(user=self.user, lookahead_days=5)

        rule = ensure_default_rule(self.user)

        self.assertEqual(rule.lookahead_days, 5)
        self.assertEqual(alarms_of(self.user), [(time(9, 0), EVERY_DAY, True)])


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class NewUserOnboardingTests(TestCase):
    """Connect Canvas -> turn on a course -> add a destination is enough to get alerts."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="new@example.com")
        self.client.force_login(self.user)

    def connect(self):
        def fake_store(*, user, token, school=None):
            return CanvasConnection.objects.create(
                user=user,
                canvas_user_id="1",
                canvas_name="New",
                encrypted_token=encrypt_secret(token),
                verified_at=timezone.now(),
            )

        with patch("accounts.views.verify_and_store_connection", side_effect=fake_store), patch(
            "accounts.views.sync_courses", return_value=CourseSelection.objects.none()
        ):
            return self.client.post(reverse("canvas_connect"), {"school": "skku", "token": "secret"})

    def test_connecting_canvas_creates_the_default_schedule(self):
        self.connect()

        self.assertEqual(alarms_of(self.user), [(time(9, 0), EVERY_DAY, True)])

    def test_failed_connection_creates_nothing(self):
        with patch("accounts.views.verify_and_store_connection", side_effect=CanvasConnectionError):
            self.client.post(reverse("canvas_connect"), {"school": "skku", "token": "bad"})

        self.assertFalse(NotificationRule.objects.filter(user=self.user).exists())

    def test_three_green_steps_mean_a_scheduled_run(self):
        self.connect()
        CourseSelection.objects.create(
            user=self.user, canvas_course_id=1, course_name="A", enabled=True, include_assignments=True
        )
        Destination.objects.create(
            user=self.user,
            kind="discord",
            encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/x"),
        )

        dashboard = self.client.get(reverse("dashboard"))
        claimed = claim_due_runs(datetime(2026, 9, 30, 0, 0, tzinfo=UTC))  # 09:00 KST

        self.assertIsNotNone(dashboard.context["next_run"])
        self.assertNotContains(dashboard, "켜 둔 알림 시각이 없어")
        self.assertEqual([run.user_id for run in claimed], [self.user.pk])

    def test_dashboard_warns_when_every_alarm_is_off(self):
        self.connect()
        CourseSelection.objects.create(
            user=self.user, canvas_course_id=1, course_name="A", enabled=True, include_assignments=True
        )
        Destination.objects.create(user=self.user, kind="discord", encrypted_webhook_url="x")
        AlarmTime.objects.filter(rule__user=self.user).update(enabled=False)

        dashboard = self.client.get(reverse("dashboard"))

        self.assertIsNone(dashboard.context["next_run"])
        self.assertContains(dashboard, "켜 둔 알림 시각이 없어서 예약 알림이 가지 않아요.")

    def test_preview_before_saving_settings_also_creates_a_usable_schedule(self):
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="New",
            encrypted_token=encrypt_secret("token"),
            verified_at=timezone.now(),
        )
        fake = FakeCanvasClient("unused", "unused")

        collect_for_user(self.user, timezone.now(), client_class=lambda _b, _t: fake)

        self.assertEqual(alarms_of(self.user), [(time(9, 0), EVERY_DAY, True)])


class DefaultAlarmMigrationTests(TransactionTestCase):
    before = [("accounts", "0008_excluded_items")]
    after = [("accounts", "0009_default_alarm_for_existing_users")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        self.migrate(executor.loader.graph.leaf_nodes())

    def test_connected_users_without_alarms_get_the_default(self):
        old = self.migrate(self.before)
        User = old.get_model("auth", "User")
        Connection = old.get_model("accounts", "CanvasConnection")
        Rule = old.get_model("accounts", "NotificationRule")
        Alarm = old.get_model("accounts", "AlarmTime")

        def connected(name):
            user = User.objects.create(username=name)
            Connection.objects.create(
                user=user, canvas_user_id=name, canvas_name=name, encrypted_token="x", verified_at=timezone.now()
            )
            return user

        no_rule = connected("no-rule")
        empty_rule = connected("empty-rule")
        Rule.objects.create(user=empty_rule, lookahead_days=6)
        configured = connected("configured")
        Alarm.objects.create(rule=Rule.objects.create(user=configured), time=time(7, 0), weekdays=1, enabled=False)
        not_connected = User.objects.create(username="not-connected")

        new = self.migrate(self.after)
        Alarm = new.get_model("accounts", "AlarmTime")
        Rule = new.get_model("accounts", "NotificationRule")

        def alarms(user):
            return list(Alarm.objects.filter(rule__user_id=user.pk).values_list("time", "weekdays", "enabled"))

        self.assertEqual(alarms(no_rule), [(time(9, 0), EVERY_DAY, True)])
        self.assertEqual(alarms(empty_rule), [(time(9, 0), EVERY_DAY, True)])
        self.assertEqual(Rule.objects.get(user_id=empty_rule.pk).lookahead_days, 6)
        self.assertEqual(alarms(configured), [(time(7, 0), 1, False)])
        self.assertFalse(Rule.objects.filter(user_id=not_connected.pk).exists())
