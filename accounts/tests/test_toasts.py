from django.contrib import messages
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ToastMarkupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)

    def test_success_message_is_a_closable_floating_toast(self):
        response = self.client.post(reverse("canvas_disconnect"), follow=True)

        self.assertContains(response, 'class="message-stack" aria-live="polite" data-toasts')
        self.assertContains(response, "Canvas 연결을 해제했습니다.")
        self.assertContains(response, 'aria-label="알림 닫기"')
        self.assertNotContains(response, 'data-toast role="alert"')

    def test_error_message_is_announced_as_alert(self):
        session_response = self.client.get(reverse("dashboard"))
        request = session_response.wsgi_request
        storage = messages.storage.default_storage(request)
        storage.add(messages.ERROR, "토큰을 확인하지 못했습니다.")
        storage.update(session_response)
        self.client.cookies.update(session_response.cookies)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-toast role="alert"')
        self.assertContains(response, "토큰을 확인하지 못했습니다.")

    def test_no_stack_without_messages(self):
        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "data-toasts")
