from types import SimpleNamespace

from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts import throttle
from accounts.adapters import PilotSocialAccountAdapter


def social_login(*addresses):
    return SimpleNamespace(
        email_addresses=[
            SimpleNamespace(email=email, verified=verified)
            for email, verified in addresses
        ]
    )


@override_settings(SIGNUP_OPEN=True, PILOT_ALLOWED_EMAILS=set())
class OpenSignupAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = PilotSocialAccountAdapter()
        self.request = RequestFactory().get("/")

    def test_any_verified_email_may_sign_up(self):
        login = social_login(("stranger@example.com", True))

        self.assertTrue(self.adapter.is_open_for_signup(self.request, login))
        self.adapter.pre_social_login(self.request, login)  # does not raise

    def test_unverified_email_is_still_refused(self):
        login = social_login(("stranger@example.com", False))

        self.assertFalse(self.adapter.is_open_for_signup(self.request, login))
        with self.assertRaises(ImmediateHttpResponse) as raised:
            self.adapter.pre_social_login(self.request, login)
        self.assertEqual(raised.exception.response.status_code, 403)

    def test_login_without_any_email_is_refused(self):
        self.assertFalse(self.adapter.is_open_for_signup(self.request, social_login()))


@override_settings(SIGNUP_OPEN=False, PILOT_ALLOWED_EMAILS={"pilot@example.com"})
class ClosedSignupAdapterTests(SimpleTestCase):
    def test_allowlist_still_applies_when_switch_is_off(self):
        adapter = PilotSocialAccountAdapter()
        request = RequestFactory().get("/")

        self.assertFalse(
            adapter.is_open_for_signup(request, social_login(("stranger@example.com", True)))
        )
        self.assertTrue(
            adapter.is_open_for_signup(request, social_login(("pilot@example.com", True)))
        )


class SignupSwitchDefaultTests(SimpleTestCase):
    def test_switch_is_off_unless_exactly_one(self):
        import importlib
        import os
        from unittest import mock

        import config.settings as settings_module

        for value, expected in (("1", True), ("0", False), ("true", False), ("", False)):
            with mock.patch.dict(os.environ, {"SIGNUP_OPEN": value}):
                self.assertIs(importlib.reload(settings_module).SIGNUP_OPEN, expected)
        importlib.reload(settings_module)


class SignupCopyTests(TestCase):
    def test_login_copy_follows_switch(self):
        with override_settings(SIGNUP_OPEN=True):
            page = Client().get(reverse("account_login")).content.decode()
        self.assertNotIn("초대받은", page)
        self.assertNotIn("파일럿 전용", page)

        with override_settings(SIGNUP_OPEN=False):
            page = Client().get(reverse("account_login")).content.decode()
        self.assertIn("초대받은 Google 계정만", page)


@override_settings(RATE_LIMITS_ENABLED=True)
class ThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="rate@example.com")
        self.client.force_login(self.user)

    def tearDown(self):
        cache.clear()

    def test_allow_counts_per_user_and_action(self):
        limit, _window = throttle.LIMITS["canvas_connect"]
        results = [throttle.allow(self.user, "canvas_connect") for _ in range(limit + 1)]

        self.assertEqual(results, [True] * limit + [False])
        self.assertTrue(throttle.allow(self.user, "preview"))
        other = get_user_model().objects.create_user(username="other@example.com")
        self.assertTrue(throttle.allow(other, "canvas_connect"))

    def test_connect_over_limit_does_not_call_canvas(self):
        limit, _window = throttle.LIMITS["canvas_connect"]
        for _ in range(limit):
            throttle.allow(self.user, "canvas_connect")

        from unittest import mock

        with mock.patch("accounts.views.verify_and_store_connection") as verify:
            response = self.client.post(reverse("canvas_connect"), {"token": "x" * 40}, follow=True)
        verify.assert_not_called()
        self.assertContains(response, "요청이 너무 많아요")

    def test_preview_over_limit_redirects_without_collecting(self):
        limit, _window = throttle.LIMITS["preview"]
        for _ in range(limit):
            throttle.allow(self.user, "preview")

        from unittest import mock

        with mock.patch("accounts.views.collect_for_user") as collect:
            response = self.client.post(reverse("preview"))
        collect.assert_not_called()
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
