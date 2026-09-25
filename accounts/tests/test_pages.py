from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PageContractTests(TestCase):
    def test_login_explains_the_two_separate_connections(self):
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, "Google로 계속")
        self.assertContains(response, "Canvas 연결")
        self.assertContains(response, "아직 알림은 시작되지 않습니다")

    def test_dashboard_has_accessible_token_form(self):
        user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'type="password"')
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, "과목 선택은 다음 단계에서 진행합니다")
