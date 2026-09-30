from datetime import UTC, datetime, time

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    EVERY_DAY,
    AlarmTime,
    CanvasConnection,
    CourseSelection,
    Destination,
    NotificationRule,
    weekdays_summary,
)
from accounts.tests.helpers import alarm_post_data, make_rule


class AlarmSettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)
        self.url = reverse("notification_settings_save")

    def save(self, *alarms, existing=(), extra=None):
        data = {"lookahead_days": "3", "kind": "discord", "webhook_url": "", **alarm_post_data(*alarms, existing=existing)}
        data.update(extra or {})
        return self.client.post(self.url, data)

    def alarms(self):
        rule = NotificationRule.objects.get(user=self.user)
        return list(rule.alarms.values_list("time", "weekdays", "enabled"))

    def test_new_user_starts_with_one_daily_alarm_row(self):
        page = self.client.get(reverse("notification_settings"))

        self.assertContains(page, 'name="alarms-TOTAL_FORMS" value="1"')
        self.assertContains(page, 'value="09:00"')
        self.assertContains(page, "+ 알림 시각 추가")
        self.assertFalse(NotificationRule.objects.filter(user=self.user).exists())

    def test_untouched_default_row_is_saved_as_an_alarm(self):
        response = self.save("09:00")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.alarms(), [(time(9, 0), EVERY_DAY, True)])

    def test_weekdays_and_off_switch_are_saved(self):
        self.save(("07:30", [0, 1, 2, 3, 4], True), ("10:00", [5, 6], False))

        self.assertEqual(
            self.alarms(),
            [(time(7, 30), 0b0011111, True), (time(10, 0), 0b1100000, False)],
        )

    def test_up_to_three_alarms_are_accepted(self):
        response = self.save("07:00", "12:00", "22:00")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.alarms()), 3)

    def test_fourth_alarm_is_rejected_and_nothing_saved(self):
        response = self.save("07:00", "09:00", "12:00", "22:00")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(NotificationRule.objects.filter(user=self.user).exists())

    def test_limit_is_three_and_page_tells_the_editor(self):
        self.assertEqual(AlarmTime.MAX_PER_RULE, 3)
        self.client.force_login(self.user)
        page = self.client.get(reverse("notification_settings"))
        self.assertContains(page, 'data-alarm-limit="3"')

    def test_alarm_without_weekday_is_rejected(self):
        response = self.save(("09:00", [], True))

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "요일을 하나 이상 선택해 주세요.", status_code=400)

    def test_deleting_every_alarm_is_rejected(self):
        rule = make_rule(self.user, time(9, 0))
        alarm = rule.alarms.get()

        response = self.save("09:00", existing=[alarm.pk], extra={"alarms-0-DELETE": "on"})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "알림 시각이 하나 이상 있어야 해요.", status_code=400)
        self.assertTrue(AlarmTime.objects.filter(pk=alarm.pk).exists())

    def test_deleting_one_of_two_alarms_keeps_the_other(self):
        rule = make_rule(self.user, time(9, 0), time(20, 0))
        first, second = rule.alarms.order_by("time")

        response = self.save(
            "09:00",
            "20:00",
            existing=[first.pk, second.pk],
            extra={"alarms-1-DELETE": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.alarms(), [(time(9, 0), EVERY_DAY, True)])

    def test_editing_an_existing_alarm_updates_it_in_place(self):
        rule = make_rule(self.user, time(9, 0))
        alarm = rule.alarms.get()

        self.save(("08:15", [0, 2, 4], True), existing=[alarm.pk])

        alarm.refresh_from_db()
        self.assertEqual((alarm.time, alarm.weekdays), (time(8, 15), 0b0010101))

    def test_other_users_alarm_cannot_be_edited(self):
        other = get_user_model().objects.create_user(username="other@example.com")
        other_alarm = make_rule(other, time(6, 0)).alarms.get()
        make_rule(self.user, time(9, 0))

        self.save("23:00", existing=[other_alarm.pk])

        other_alarm.refresh_from_db()
        self.assertEqual(other_alarm.time, time(6, 0))

    def test_settings_page_renders_saved_alarms_with_weekday_chips(self):
        make_rule(self.user, time(7, 30), weekdays=0b0011111)

        page = self.client.get(reverse("notification_settings"))

        self.assertContains(page, 'value="07:30"')
        self.assertContains(page, 'class="day-chip"', count=14)  # saved row + add template
        self.assertContains(page, 'name="alarms-0-days" value="0"')


class WeekdaySummaryTests(TestCase):
    def test_summaries(self):
        self.assertEqual(weekdays_summary(EVERY_DAY), "매일")
        self.assertEqual(weekdays_summary(0b0011111), "평일")
        self.assertEqual(weekdays_summary(0b1100000), "주말")
        self.assertEqual(weekdays_summary(0b0000101), "월 수")


class DashboardChecklistTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)

    def test_google_step_is_not_in_the_checklist(self):
        page = self.client.get(reverse("dashboard"))

        self.assertNotContains(page, "<strong>Google</strong>")
        self.assertContains(page, '<span class="status-number" aria-hidden="true">3</span>')
        self.assertNotContains(page, '<span class="status-number" aria-hidden="true">4</span>')

    def test_next_run_summary_lists_active_alarms_only(self):
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token="x",
            verified_at=timezone.now(),
        )
        CourseSelection.objects.create(
            user=self.user, canvas_course_id=1, course_name="A", enabled=True, include_assignments=True
        )
        Destination.objects.create(user=self.user, kind="discord", encrypted_webhook_url="x")
        rule = make_rule(self.user, time(7, 30), weekdays=0b0011111)
        AlarmTime.objects.create(rule=rule, time=time(21, 0), enabled=False)

        page = self.client.get(reverse("dashboard"))

        self.assertContains(page, "07:30 평일")
        self.assertNotContains(page, "21:00")


class AlarmMigrationTests(TransactionTestCase):
    """0007 turns first_time/second_time into daily alarm rows, and back."""

    before = [("accounts", "0006_multi_destination_webpush")]
    after = [("accounts", "0007_alarm_times")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        self.migrate(executor_leaf())

    def test_existing_times_become_daily_alarms_and_reverse(self):
        old_apps = self.migrate(self.before)
        User = old_apps.get_model("auth", "User")
        Rule = old_apps.get_model("accounts", "NotificationRule")
        two = Rule.objects.create(
            user=User.objects.create(username="two@example.com"),
            first_time=time(9, 0),
            second_time=time(20, 0),
        )
        one = Rule.objects.create(
            user=User.objects.create(username="one@example.com"),
            first_time=time(7, 15),
            second_time=None,
        )

        new_apps = self.migrate(self.after)
        Alarm = new_apps.get_model("accounts", "AlarmTime")
        self.assertEqual(
            list(Alarm.objects.filter(rule_id=two.pk).order_by("time").values_list("time", "weekdays", "enabled")),
            [(time(9, 0), EVERY_DAY, True), (time(20, 0), EVERY_DAY, True)],
        )
        self.assertEqual(
            list(Alarm.objects.filter(rule_id=one.pk).values_list("time", flat=True)),
            [time(7, 15)],
        )

        reverted = self.migrate(self.before).get_model("accounts", "NotificationRule")
        restored = reverted.objects.get(pk=two.pk)
        self.assertEqual((restored.first_time, restored.second_time), (time(9, 0), time(20, 0)))


def executor_leaf():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()


class SchedulerIntegrationTests(TestCase):
    def test_weekend_only_alarm_is_not_claimed_on_a_weekday(self):
        from cryptography.fernet import Fernet
        from django.test import override_settings

        from accounts.scheduling import claim_due_runs
        from accounts.services import encrypt_secret

        with override_settings(CREDENTIAL_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            user = get_user_model().objects.create_user(username="pilot@example.com")
            CanvasConnection.objects.create(
                user=user,
                canvas_user_id="1",
                canvas_name="Pilot",
                encrypted_token=encrypt_secret("token"),
                verified_at=timezone.now(),
            )
            CourseSelection.objects.create(
                user=user, canvas_course_id=1, course_name="A", enabled=True, include_assignments=True
            )
            Destination.objects.create(
                user=user,
                kind="discord",
                encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/x"),
            )
            make_rule(user, time(9, 0), weekdays=0b1100000)

            monday_0900 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
            saturday_0900 = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)

            self.assertEqual(claim_due_runs(monday_0900), ())
            self.assertEqual(len(claim_due_runs(saturday_0900)), 1)


class AssetVersionTests(TestCase):
    def test_css_and_js_urls_carry_a_content_version(self):
        from config.context_processors import _asset_version

        user = get_user_model().objects.create_user(username="assets@example.com")
        self.client.force_login(user)
        page = self.client.get(reverse("notification_settings"))

        version = _asset_version()
        self.assertRegex(version, r"^[0-9a-f]{12}$")
        self.assertContains(page, f"app.css?v={version}")
        self.assertContains(page, f"app.js?v={version}")
        self.assertNotContains(page, "휴대폰 알람처럼")
