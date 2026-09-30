from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


class TermsOfServiceTests(TestCase):
    def test_terms_are_public(self):
        page = Client().get(reverse("terms_of_service"))

        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        for heading in ("서비스 내용", "가입과 계정", "지켜 주실 것", "알림의 한계", "서비스와 약관의 변경", "문의"):
            self.assertIn(heading, body)
        self.assertIn("비공식 서비스", body)
        self.assertIn("성균관대학교", body)
        self.assertIn(reverse("privacy_policy"), body)

    def test_contact_email_is_optional(self):
        with override_settings(PRIVACY_CONTACT_EMAIL=""):
            body = Client().get(reverse("terms_of_service")).content.decode()
        self.assertNotIn("mailto:", body)
        self.assertIn("운영자에게", body)

        with override_settings(PRIVACY_CONTACT_EMAIL="help@example.com"):
            body = Client().get(reverse("terms_of_service")).content.decode()
        self.assertIn("mailto:help@example.com", body)


class SiteFooterTests(TestCase):
    def assert_footer(self, body, email=None):
        footer = body[body.index('<footer class="site-footer">'):]
        footer = footer[: footer.index("</footer>")]
        self.assertIn(reverse("terms_of_service"), footer)
        self.assertIn(reverse("privacy_policy"), footer)
        self.assertIn(reverse("canvas_token_guide"), footer)
        self.assertIn(reverse("pwa_install_guide"), footer)
        self.assertIn("비공식 서비스", footer)
        if email:
            self.assertIn(f"mailto:{email}", footer)
        else:
            self.assertNotIn("mailto:", footer)

    @override_settings(PRIVACY_CONTACT_EMAIL="help@example.com")
    def test_footer_on_public_pages(self):
        for name in ("account_login", "privacy_policy", "terms_of_service", "canvas_token_guide"):
            with self.subTest(page=name):
                self.assert_footer(Client().get(reverse(name)).content.decode(), "help@example.com")

    @override_settings(PRIVACY_CONTACT_EMAIL="")
    def test_footer_without_contact_email(self):
        self.assert_footer(Client().get(reverse("account_login")).content.decode())

    def test_footer_for_signed_in_user(self):
        user = get_user_model().objects.create_user("footer", "footer@example.com", "x")
        client = Client()
        client.force_login(user)

        page = client.get(reverse("dashboard"), follow=True)

        self.assertEqual(page.status_code, 200)
        self.assert_footer(page.content.decode())
