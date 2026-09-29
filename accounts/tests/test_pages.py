from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PageContractTests(TestCase):
    def test_healthz_is_public_and_minimal(self):
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/plain")
        self.assertEqual(response.content, b"ok\n")

    def test_login_offers_google_and_points_to_the_canvas_token_step(self):
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, "Google로 계속하기")
        self.assertContains(response, "Canvas 액세스 토큰")
        self.assertContains(response, reverse("canvas_token_guide"))
        self.assertContains(response, "초대받은 Google 계정만")
        self.assertNotContains(response, "두 연결은 서로 다릅니다")

    def test_dashboard_has_accessible_token_form(self):
        user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'type="password"')
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, "과목 선택")
        self.assertContains(response, "알림 설정")
        self.assertContains(response, 'aria-label="주 메뉴"')
