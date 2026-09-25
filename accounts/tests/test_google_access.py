from types import SimpleNamespace

from allauth.core.exceptions import ImmediateHttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from accounts.adapters import PilotSocialAccountAdapter


def social_login(*addresses):
    return SimpleNamespace(
        email_addresses=[
            SimpleNamespace(email=email, verified=verified)
            for email, verified in addresses
        ]
    )


@override_settings(PILOT_ALLOWED_EMAILS={"pilot@example.com"})
class PilotSocialAccountAdapterTests(SimpleTestCase):
    def setUp(self):
        self.adapter = PilotSocialAccountAdapter()
        self.request = RequestFactory().get("/")

    def test_verified_allowlisted_email_is_open(self):
        login = social_login((" Pilot@Example.com ", True))

        self.assertTrue(self.adapter.is_open_for_signup(self.request, login))

    def test_unverified_email_is_closed(self):
        login = social_login(("pilot@example.com", False))

        self.assertFalse(self.adapter.is_open_for_signup(self.request, login))

    def test_existing_disallowed_login_is_denied_without_echoing_email(self):
        with self.assertRaises(ImmediateHttpResponse) as raised:
            self.adapter.pre_social_login(
                self.request,
                social_login(("other@example.com", True)),
            )

        response = raised.exception.response
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"other@example.com", response.content)
