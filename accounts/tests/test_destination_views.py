import socket
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Destination
from accounts.notifications import AmbiguousDeliveryError, DefiniteDeliveryError
from accounts.services import decrypt_secret, encrypt_secret


KEY = Fernet.generate_key().decode()
PUBLIC_DNS = [
    (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("93.184.216.34", 443),
    )
]


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class DestinationViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        self.discord_url = "https://discord.com/api/webhooks/123/secret-token"
        self.slack_url = "https://hooks.slack.com/services/T1/B2/secret"
        self.client.force_login(self.user)

    def create_destination(self, user=None, *, kind=Destination.Kind.DISCORD, url=None):
        return Destination.objects.create(
            user=user or self.user,
            kind=kind,
            encrypted_webhook_url=encrypt_secret(url or self.discord_url),
        )

    def test_create_requires_url(self):
        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.DISCORD, "webhook_url": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Destination.objects.filter(user=self.user).exists())

    @patch("accounts.views.send_webhook_part")
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_create_encrypts_without_sending_or_rendering_url(self, _dns, send):
        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.DISCORD, "webhook_url": self.discord_url},
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard"))
        destination = Destination.objects.get(user=self.user)
        self.assertEqual(decrypt_secret(destination.encrypted_webhook_url), self.discord_url)
        self.assertNotEqual(destination.encrypted_webhook_url, self.discord_url)
        self.assertEqual(destination.status, Destination.Status.UNTESTED)
        send.assert_not_called()
        self.assertNotContains(response, self.discord_url)
        self.assertNotContains(response, destination.encrypted_webhook_url)

    def test_blank_update_preserves_ciphertext_for_same_provider(self):
        destination = self.create_destination()
        original_ciphertext = destination.encrypted_webhook_url

        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.DISCORD, "webhook_url": ""},
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard"))
        destination.refresh_from_db()
        self.assertEqual(destination.encrypted_webhook_url, original_ciphertext)
        self.assertEqual(destination.kind, Destination.Kind.DISCORD)

    def test_changing_provider_with_blank_url_is_rejected_and_preserves_row(self):
        destination = self.create_destination()
        original_ciphertext = destination.encrypted_webhook_url

        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.SLACK, "webhook_url": ""},
        )

        self.assertEqual(response.status_code, 400)
        destination.refresh_from_db()
        self.assertEqual(destination.kind, Destination.Kind.DISCORD)
        self.assertEqual(destination.encrypted_webhook_url, original_ciphertext)

    def test_delete_removes_only_current_users_destination(self):
        own = self.create_destination()
        other = self.create_destination(
            self.other,
            kind=Destination.Kind.SLACK,
            url=self.slack_url,
        )

        response = self.client.post(reverse("destination_delete"))

        self.assertRedirects(
            response,
            reverse("dashboard"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Destination.objects.filter(pk=own.pk).exists())
        self.assertTrue(Destination.objects.filter(pk=other.pk).exists())

    def test_test_route_rejects_get(self):
        self.assertEqual(self.client.get(reverse("destination_test")).status_code, 405)

    def test_test_route_requires_csrf(self):
        self.create_destination()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        self.assertEqual(client.post(reverse("destination_test")).status_code, 403)

    @patch("accounts.views.send_webhook_part", return_value="message-1")
    def test_explicit_test_posts_once_and_marks_success(self, send):
        destination = self.create_destination()

        response = self.client.post(reverse("destination_test"), follow=True)

        self.assertRedirects(response, reverse("dashboard"))
        send.assert_called_once_with(
            Destination.Kind.DISCORD,
            self.discord_url,
            "LearningX Alert 시험 알림입니다.",
        )
        destination.refresh_from_db()
        self.assertEqual(destination.status, Destination.Status.SUCCEEDED)
        self.assertIsNotNone(destination.last_tested_at)
        self.assertContains(response, "시험 알림 전송을 확인했습니다.")
        self.assertNotContains(response, self.discord_url)

    def test_test_result_statuses_use_safe_messages_and_timestamp(self):
        destination = self.create_destination()
        cases = (
            (
                DefiniteDeliveryError("exception-secret-definite"),
                Destination.Status.DEFINITELY_FAILED,
                "시험 알림 전송에 실패했습니다.",
            ),
            (
                AmbiguousDeliveryError("exception-secret-ambiguous"),
                Destination.Status.NEEDS_REVIEW,
                "전송 결과를 확인할 수 없습니다. 대상 채널을 직접 확인해 주세요.",
            ),
        )
        for error, expected_status, safe_message in cases:
            with self.subTest(status=expected_status), patch(
                "accounts.views.send_webhook_part",
                side_effect=error,
            ) as send:
                response = self.client.post(reverse("destination_test"), follow=True)
                send.assert_called_once()
                destination.refresh_from_db()
                self.assertEqual(destination.status, expected_status)
                self.assertIsNotNone(destination.last_tested_at)
                self.assertContains(response, safe_message)
                self.assertNotContains(response, str(error))
                self.assertNotContains(response, self.discord_url)
                self.assertNotContains(response, destination.encrypted_webhook_url)

    @patch("accounts.views.send_webhook_part")
    def test_other_users_destination_is_never_tested_or_rendered(self, send):
        other = self.create_destination(self.other)

        response = self.client.post(reverse("destination_test"), follow=True)

        send.assert_not_called()
        self.assertContains(response, "알림 대상을 먼저 저장해 주세요.")
        self.assertNotContains(response, self.discord_url)
        self.assertNotContains(response, other.encrypted_webhook_url)
