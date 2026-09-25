from django.test import TestCase
from django.urls import reverse


class DashboardShellTests(TestCase):
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f'{reverse("account_login")}?next=/')
