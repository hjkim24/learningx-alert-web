import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CanvasConnection, CourseSelection, Destination, ScheduledRun
from accounts.tests.helpers import make_rule


class GettingStartedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="new@example.com")
        self.client.force_login(self.user)

    def connect(self, user=None):
        user = user or self.user
        make_rule(user)
        return CanvasConnection.objects.create(
            user=user, canvas_user_id="1", canvas_name="학생",
            encrypted_token="not-needed-on-get", verified_at=timezone.now(),
        )

    def select_course(self, user=None):
        return CourseSelection.objects.create(
            user=user or self.user, canvas_course_id=1, course_name="과목",
            enabled=True, include_assignments=True,
        )

    def add_destination(self, status=Destination.Status.UNTESTED, user=None):
        return Destination.objects.create(
            user=user or self.user, kind=Destination.Kind.WEBPUSH,
            encrypted_webhook_url="not-needed-on-get", status=status,
        )

    def dashboard(self):
        page = self.client.get(reverse("dashboard"))
        self.assertIn("setup_step", page.context)
        return page

    def test_new_user_starts_with_connection_and_expanded_guide(self):
        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 1)
        self.assertEqual(page.context["setup_completed_count"], 0)
        self.assertContains(page, 'aria-current="step"', count=1)
        self.assertContains(page, 'id="start-guide" open')
        self.assertContains(page, 'href="#canvas-title"')

    def test_connected_user_is_directed_to_course_selection(self):
        self.connect()

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 2)
        self.assertEqual(page.context["setup_completed_count"], 1)
        self.assertContains(page, reverse("course_settings"))

    def test_selected_courses_lead_to_destination_registration(self):
        self.connect()
        self.select_course()

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 3)
        self.assertEqual(page.context["setup_completed_count"], 2)
        self.assertContains(page, reverse("destination_settings"))

    def test_saved_destination_still_requires_an_explicit_test(self):
        self.connect()
        self.select_course()
        self.add_destination()

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 4)
        self.assertEqual(page.context["setup_completed_count"], 3)
        self.assertContains(page, reverse("destination_settings") + "#destination-status-title")
        self.assertFalse(ScheduledRun.objects.exists())
        self.assertEqual(Destination.objects.get(user=self.user).status, "untested")

    def test_failed_or_ambiguous_test_does_not_complete_setup(self):
        self.connect()
        self.select_course()
        target = self.add_destination()
        for status in ("definitely_failed", "needs_review"):
            with self.subTest(status=status):
                target.status = status
                target.save(update_fields=("status",))
                page = self.dashboard()
                self.assertEqual(page.context["setup_step"], 4)
                self.assertFalse(page.context["setup_test_succeeded"])

    def test_successful_test_collapses_reopenable_guide(self):
        self.connect()
        self.select_course()
        self.add_destination(Destination.Status.SUCCEEDED)

        page = self.dashboard()

        self.assertIsNone(page.context["setup_step"])
        self.assertEqual(page.context["setup_completed_count"], 4)
        self.assertNotContains(page, 'aria-current="step"')
        tag = re.search(r'<details[^>]*id="start-guide"[^>]*>', page.content.decode())
        self.assertIsNotNone(tag)
        self.assertNotIn(" open", tag.group())
        self.assertContains(page, reverse("canvas_token_guide"))
        self.assertContains(page, reverse("pwa_install_guide"))

    def test_disabled_schedule_requires_schedule_settings_after_test(self):
        self.connect()
        self.select_course()
        self.add_destination(Destination.Status.SUCCEEDED)
        self.user.notification_rule.alarms.update(enabled=False)

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 4)
        self.assertEqual(page.context["setup_completed_count"], 3)
        self.assertContains(page, "알림 시각 켜기")
        self.assertContains(page, reverse("notification_settings"))

    def test_rejected_token_returns_to_connection_even_with_other_steps_saved(self):
        connection = self.connect()
        connection.needs_reconnect = True
        connection.save(update_fields=("needs_reconnect",))
        self.select_course()
        self.add_destination(Destination.Status.SUCCEEDED)

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 1)
        self.assertContains(page, 'aria-current="step"', count=1)
        self.assertContains(page, 'id="start-guide" open')

    def test_another_users_settings_do_not_advance_progress(self):
        other = get_user_model().objects.create_user(username="other@example.com")
        self.connect(other)
        self.select_course(other)
        self.add_destination(Destination.Status.SUCCEEDED, other)

        page = self.dashboard()

        self.assertEqual(page.context["setup_step"], 1)
        self.assertEqual(page.context["setup_completed_count"], 0)

    def test_one_successful_current_destination_is_enough(self):
        self.connect()
        self.select_course()
        self.add_destination()
        self.add_destination(Destination.Status.SUCCEEDED)

        self.assertIsNone(self.dashboard().context["setup_step"])


class LoginGettingStartedTests(TestCase):
    @override_settings(ENABLED_SCHOOLS=("hanyang",))
    def test_intro_lists_only_enabled_schools_and_keeps_existing_guides(self):
        page = self.client.get(reverse("account_login"))

        self.assertContains(page, "한양대학교")
        self.assertNotContains(page, "성균관대학교")
        self.assertContains(page, 'href="#how-to-start"')
        self.assertContains(page, 'id="how-to-start"')
        self.assertContains(page, reverse("canvas_token_guide"))
        self.assertContains(page, reverse("pwa_install_guide"))
        self.assertContains(page, "Google로 계속하기")
