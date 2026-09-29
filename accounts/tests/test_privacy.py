from django.test import Client, TestCase, override_settings
from django.urls import reverse


class PrivacyPolicyTests(TestCase):
    def test_policy_is_public(self):
        page = Client().get(reverse("privacy_policy"))

        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        for heading in ("받는 정보", "쓰는 곳", "정보가 거쳐 가는 곳", "보관과 삭제", "문의"):
            self.assertIn(heading, body)
        self.assertIn("api-services-user-data-policy", body)
        self.assertIn("14일", body)

    def test_login_page_links_to_policy(self):
        page = Client().get(reverse("account_login")).content.decode()

        self.assertIn(reverse("privacy_policy"), page)

    def test_contact_email_is_optional(self):
        with override_settings(PRIVACY_CONTACT_EMAIL=""):
            body = Client().get(reverse("privacy_policy")).content.decode()
        self.assertNotIn("mailto:", body)
        self.assertIn("운영자에게", body)

        with override_settings(PRIVACY_CONTACT_EMAIL="help@example.com"):
            body = Client().get(reverse("privacy_policy")).content.decode()
        self.assertIn("mailto:help@example.com", body)
