from io import StringIO

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Feedback, ScheduledRun
from accounts.views import _client_label

IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


class FeedbackSubmitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fb@example.com", email="fb@example.com"
        )
        self.client.force_login(self.user)

    def post(self, **data):
        payload = {"category": "bug", "message": "푸시가 안 와요", "include_context": "1",
                   "page_path": "/connection/destinations/?code=secret", "standalone": "1"}
        payload.update(data)
        return self.client.post(
            reverse("feedback"), payload, HTTP_ACCEPT="application/json",
            HTTP_USER_AGENT=IPHONE_SAFARI,
        )

    @override_settings(APP_REVISION="abc1234def")
    def test_json_submit_stores_feedback_with_reduced_context_and_logs_no_text(self):
        run = ScheduledRun.objects.create(user=self.user, scheduled_for="2026-09-30T00:00Z")
        with self.assertLogs("accounts.views", level="WARNING") as logs:
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        entry = Feedback.objects.get()
        self.assertEqual(entry.category, "bug")
        self.assertEqual(entry.page_path, "/connection/destinations/")  # query dropped
        self.assertEqual(entry.client, "Safari · iOS")  # never the raw User-Agent
        self.assertTrue(entry.standalone)
        self.assertEqual(entry.app_revision, "abc1234def")
        self.assertEqual(entry.latest_run_id, run.pk)
        self.assertIn("feedback received", logs.output[0])
        self.assertNotIn("푸시가 안 와요", "".join(logs.output))

    def test_context_is_left_out_when_unchecked(self):
        self.post(include_context="")

        entry = Feedback.objects.get()
        self.assertEqual((entry.page_path, entry.client, entry.app_revision), ("", "", ""))
        self.assertIsNone(entry.latest_run_id)
        self.assertIsNone(entry.standalone)

    def test_invalid_input_is_rejected(self):
        self.assertEqual(self.post(category="spam").status_code, 400)
        self.assertEqual(self.post(message="  ").status_code, 400)
        self.assertEqual(self.post(message="가" * 2001).status_code, 400)
        self.assertFalse(Feedback.objects.exists())

    def test_foreign_urls_keep_only_their_same_site_path(self):
        self.post(page_path="//evil.example/x")
        self.post(page_path="https://evil.example/x")

        # The host is split off, so only a path on this site survives.
        self.assertEqual(list(Feedback.objects.values_list("page_path", flat=True)), ["/x", "/x"])

    @override_settings(RATE_LIMITS_ENABLED=True)
    def test_rate_limited_after_three_in_ten_minutes(self):
        cache.clear()
        codes = [self.post().status_code for _ in range(4)]
        cache.clear()

        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(Feedback.objects.count(), 3)

    def test_no_js_fallback_page_and_redirect(self):
        page = self.client.get(reverse("feedback"), {"from": "/connection/courses/"})
        self.assertContains(page, 'value="/connection/courses/"')

        response = self.client.post(
            reverse("feedback"), {"category": "idea", "message": "다크 모드", "page_path": "/connection/courses/"}
        )
        self.assertRedirects(response, "/connection/courses/", fetch_redirect_response=False)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse("feedback"), {"category": "bug", "message": "x"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Feedback.objects.exists())

    def test_button_shows_for_signed_in_pages_only(self):
        self.assertContains(self.client.get(reverse("dashboard")), "data-feedback-open")
        self.assertNotContains(self.client.get(reverse("privacy_policy")), "data-feedback-open")
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("account_login")), "data-feedback-open")

    def test_client_label_is_coarse(self):
        self.assertEqual(_client_label(IPHONE_SAFARI), "Safari · iOS")
        self.assertEqual(
            _client_label("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/140.0 Safari/537.36 Edg/140.0"),
            "Edge · Windows",
        )
        self.assertEqual(_client_label(""), "기타 · 기타")


@override_settings(ADMIN_EMAILS=frozenset({"admin@example.com"}))
class FeedbackAdminTests(TestCase):
    def setUp(self):
        self.admin_url = reverse("feedback_admin:accounts_feedback_changelist")
        self.reporter = get_user_model().objects.create_user(username="r@example.com", email="r@example.com")
        Feedback.objects.create(user=self.reporter, category="bug", message="보고 내용")

    def make_user(self, email, *, staff, verified=True):
        user = get_user_model().objects.create_user(username=email, email=email, is_staff=staff)
        EmailAddress.objects.create(user=user, email=email, verified=verified, primary=True)
        return user

    def test_allowlisted_verified_staff_sees_feedback(self):
        self.client.force_login(self.make_user("admin@example.com", staff=True))

        page = self.client.get(self.admin_url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "보고 내용")

    def test_every_other_combination_is_refused(self):
        for email, staff, verified in (
            ("admin@example.com", False, True),   # not staff
            ("other@example.com", True, True),    # staff but not allowlisted
        ):
            with self.subTest(email=email, staff=staff):
                self.client.force_login(self.make_user(email, staff=staff, verified=verified))
                response = self.client.get(self.admin_url, follow=True)
                self.assertEqual(response.status_code, 404)
                self.client.logout()

    def test_unverified_allowlisted_email_is_refused(self):
        user = get_user_model().objects.create_user(username="u", email="admin@example.com", is_staff=True)
        EmailAddress.objects.create(user=user, email="admin@example.com", verified=False, primary=True)
        self.client.force_login(user)

        self.assertEqual(self.client.get(self.admin_url, follow=True).status_code, 404)

    def test_anonymous_visitor_is_sent_to_google_sign_in(self):
        response = self.client.get(self.admin_url, follow=True)

        self.assertEqual(response.redirect_chain[-1][0].split("?")[0], reverse("account_login"))

    def test_admin_has_no_password_login_and_no_other_models(self):
        response = self.client.get(reverse("feedback_admin:login"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

        from accounts.admin_site import feedback_admin_site

        self.assertEqual([model.__name__ for model in feedback_admin_site._registry], ["Feedback"])

    def test_admin_cannot_add_or_delete(self):
        self.client.force_login(self.make_user("admin@example.com", staff=True))

        self.assertEqual(self.client.get(reverse("feedback_admin:accounts_feedback_add")).status_code, 403)


class FeedbackCommandAndCopyTests(TestCase):
    def test_list_and_mark_done(self):
        user = get_user_model().objects.create_user(username="c@example.com", email="c@example.com")
        entry = Feedback.objects.create(user=user, category="idea", message="첫 줄\n둘째 줄", page_path="/")

        out = StringIO()
        call_command("list_feedback", stdout=out)
        self.assertIn(f"#{entry.pk} [의견]", out.getvalue())
        self.assertIn("| 둘째 줄", out.getvalue())

        call_command("list_feedback", "--done", str(entry.pk), stdout=StringIO())
        out = StringIO()
        call_command("list_feedback", stdout=out)
        self.assertIn("no feedback", out.getvalue())

    @override_settings(PRIVACY_CONTACT_EMAIL="help@example.com")
    def test_login_page_links_contact_email_and_policy_mentions_feedback(self):
        self.assertContains(self.client.get(reverse("account_login")), "mailto:help@example.com")
        self.assertContains(self.client.get(reverse("privacy_policy")), "보내 주신 의견")
