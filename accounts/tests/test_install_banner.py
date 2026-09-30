from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Destination
from accounts.services import encrypt_secret

KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], WEB_PUSH_ENABLED=True)
class InstallBannerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="banner@example.com")

    def test_signed_in_pages_carry_the_hidden_banner_with_push_details(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "data-install-banner hidden")
        self.assertContains(response, f'data-subscribe-url="{reverse("push_subscribe")}"')
        self.assertContains(response, 'data-has-push="0"')
        for variant in ("ios-inapp", "ios-add", "enable-push", "android-install"):
            self.assertContains(response, f'data-variant="{variant}" hidden')

    def test_has_push_reflects_an_existing_browser_push_destination(self):
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.WEBPUSH,
            encrypted_webhook_url=encrypt_secret('{"endpoint": "https://push.example/1"}'),
        )
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("dashboard")), 'data-has-push="1"')

    def test_not_on_the_push_settings_page_or_for_anonymous_visitors(self):
        self.assertNotContains(self.client.get(reverse("account_login")), "data-install-banner")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("destination_settings")), "data-install-banner")

    @override_settings(WEB_PUSH_ENABLED=False)
    def test_not_shown_when_push_is_disabled(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("dashboard")), "data-install-banner")
