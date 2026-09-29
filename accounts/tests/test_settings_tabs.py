from datetime import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Destination
from accounts.tests.helpers import make_rule


class SettingsTabTests(TestCase):
    """알림 설정 is split into 알림 시각 (batch save) and 받을 곳 (instant actions)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pilot@example.com", email="pilot@example.com"
        )
        self.client.force_login(self.user)

    def test_both_tabs_link_to_each_other_and_mark_the_active_one(self):
        schedule = self.client.get(reverse("notification_settings"))
        destinations = self.client.get(reverse("destination_settings"))

        for page in (schedule, destinations):
            self.assertContains(page, 'class="sub-tabs"')
            self.assertContains(page, f'href="{reverse("notification_settings")}"')
            self.assertContains(page, f'href="{reverse("destination_settings")}"')
        self.assertContains(schedule, 'aria-current="page">알림 시각</a>')
        self.assertContains(destinations, "받을 곳", html=False)
        self.assertContains(destinations, 'aria-current="page">\n    받을 곳')

    def test_schedule_tab_holds_only_batch_saved_settings(self):
        page = self.client.get(reverse("notification_settings"))

        self.assertContains(page, "마감 조회 범위")
        self.assertContains(page, "data-alarm-editor")
        self.assertContains(page, "data-save-bar")
        self.assertNotContains(page, "data-save-bar data-dirty")
        for moved in ("webhook_url", "data-push", "destination-list", "account_delete", "계정 삭제"):
            self.assertNotContains(page, moved)

    def test_destinations_tab_holds_instant_actions_and_no_save_bar(self):
        Destination.objects.create(
            user=self.user, kind="discord", label="과제 채널", encrypted_webhook_url="x"
        )

        page = self.client.get(reverse("destination_settings"))

        self.assertContains(page, "과제 채널")
        self.assertContains(page, "data-push")
        self.assertContains(page, f'action="{reverse("destination_save")}"')
        self.assertContains(page, '<span class="tab-count">1</span>')
        self.assertNotContains(page, "data-save-bar")
        self.assertNotContains(page, "data-alarm-editor")

    def test_webhook_errors_rerender_the_destinations_tab_open(self):
        response = self.client.post(
            reverse("destination_save"), {"kind": "discord", "webhook_url": ""}
        )

        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "accounts/destination_settings.html")
        self.assertContains(response, '<details class="panel webhook-panel" open>', status_code=400)

    def test_failed_schedule_save_shows_the_save_bar_immediately(self):
        make_rule(self.user, time(9, 0))

        response = self.client.post(
            reverse("notification_settings_save"),
            {"lookahead_days": "99", "alarms-TOTAL_FORMS": "0", "alarms-INITIAL_FORMS": "0"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "data-save-bar data-dirty", status_code=400)

    def test_tabs_require_login(self):
        self.client.logout()
        for name in ("notification_settings", "destination_settings", "account_settings"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, f'{reverse("account_login")}?next={reverse(name)}')


class AccountPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pilot@example.com", email="pilot@example.com"
        )
        self.client.force_login(self.user)

    def test_header_email_links_to_account_page_and_logout_stays(self):
        page = self.client.get(reverse("dashboard"))

        self.assertContains(page, f'href="{reverse("account_settings")}"')
        self.assertContains(page, f'action="{reverse("account_logout")}"')

    def test_account_page_has_logout_and_delete(self):
        page = self.client.get(reverse("account_settings"))

        self.assertContains(page, "pilot@example.com")
        self.assertContains(page, f'action="{reverse("account_delete")}"')
        self.assertContains(page, "되돌릴 수 없습니다")


class DashboardDestinationLinkTests(TestCase):
    def test_destination_step_links_to_destinations_tab(self):
        user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(user)

        page = self.client.get(reverse("dashboard"))

        self.assertContains(page, f'<a href="{reverse("destination_settings")}">')
