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
PRIVATE_DNS = [
    (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("127.0.0.1", 443),
    )
]


class UnexpectedOpener:
    def open(self, request, timeout=30):
        raise RuntimeError("unexpected sender failure")


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

    @patch("accounts.views.send_to_destination")
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_create_encrypts_without_sending_or_rendering_url(self, _dns, send):
        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.DISCORD, "webhook_url": self.discord_url},
            follow=True,
        )

        self.assertRedirects(response, reverse("destination_settings"))
        destination = Destination.objects.get(user=self.user)
        self.assertEqual(decrypt_secret(destination.encrypted_webhook_url), self.discord_url)
        self.assertNotEqual(destination.encrypted_webhook_url, self.discord_url)
        self.assertEqual(destination.status, Destination.Status.UNTESTED)
        send.assert_not_called()
        self.assertNotContains(response, self.discord_url)
        self.assertNotContains(response, destination.encrypted_webhook_url)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_second_webhook_is_added_alongside_the_first(self, _dns):
        first = self.create_destination()

        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.SLACK, "webhook_url": self.slack_url, "label": "팀"},
            follow=True,
        )

        self.assertRedirects(response, reverse("destination_settings"))
        self.assertEqual(Destination.objects.filter(user=self.user).count(), 2)
        first.refresh_from_db()
        self.assertEqual(decrypt_secret(first.encrypted_webhook_url), self.discord_url)
        added = Destination.objects.exclude(pk=first.pk).get(user=self.user)
        self.assertEqual((added.kind, added.label), (Destination.Kind.SLACK, "팀"))
        self.assertNotContains(response, self.slack_url)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_same_webhook_twice_is_rejected(self, _dns):
        payload = {"kind": Destination.Kind.DISCORD, "webhook_url": self.discord_url}
        self.client.post(reverse("destination_save"), payload)

        response = self.client.post(reverse("destination_save"), payload)

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "이미 등록한 웹훅이에요.", status_code=400)
        self.assertEqual(Destination.objects.filter(user=self.user).count(), 1)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_destination_limit_is_enforced(self, _dns):
        self.assertEqual(Destination.MAX_PER_USER, 3)
        for index in range(Destination.MAX_PER_USER):
            self.create_destination(url=f"https://discord.com/api/webhooks/{index}/token")

        response = self.client.post(
            reverse("destination_save"),
            {"kind": Destination.Kind.DISCORD, "webhook_url": self.discord_url},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "알림 대상은 최대 3개까지 등록할 수 있어요.", status_code=400)
        self.assertEqual(
            Destination.objects.filter(user=self.user).count(),
            Destination.MAX_PER_USER,
        )

    def test_delete_of_another_users_destination_is_a_no_op(self):
        other = self.create_destination(self.other)

        self.client.post(reverse("destination_delete", args=[other.pk]))

        self.assertTrue(Destination.objects.filter(pk=other.pk).exists())

    def test_delete_removes_only_current_users_destination(self):
        own = self.create_destination()
        other = self.create_destination(
            self.other,
            kind=Destination.Kind.SLACK,
            url=self.slack_url,
        )

        response = self.client.post(reverse("destination_delete", args=[own.pk]))

        self.assertRedirects(
            response,
            reverse("destination_settings"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Destination.objects.filter(pk=own.pk).exists())
        self.assertTrue(Destination.objects.filter(pk=other.pk).exists())

    def test_test_route_rejects_get(self):
        pk = self.create_destination().pk
        self.assertEqual(self.client.get(reverse("destination_test", args=[pk])).status_code, 405)

    def test_test_route_requires_csrf(self):
        pk = self.create_destination().pk
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        self.assertEqual(client.post(reverse("destination_test", args=[pk])).status_code, 403)

    @patch("accounts.views.send_to_destination", return_value="message-1")
    def test_explicit_test_posts_once_and_marks_success(self, send):
        destination = self.create_destination()
        pk = destination.pk

        response = self.client.post(reverse("destination_test", args=[pk]), follow=True)

        self.assertRedirects(response, reverse("destination_settings"))
        send.assert_called_once_with(
            Destination.Kind.DISCORD,
            self.discord_url,
            "LearningX Alert 시험 알림이에요.",
        )
        destination.refresh_from_db()
        self.assertEqual(destination.status, Destination.Status.SUCCEEDED)
        self.assertIsNotNone(destination.last_tested_at)
        self.assertContains(response, "시험 알림을 보냈어요.")
        self.assertNotContains(response, self.discord_url)

    def test_test_result_statuses_use_safe_messages_and_timestamp(self):
        destination = self.create_destination()
        pk = destination.pk
        cases = (
            (
                DefiniteDeliveryError("exception-secret-definite"),
                Destination.Status.DEFINITELY_FAILED,
                "시험 알림을 보내지 못했어요.",
            ),
            (
                AmbiguousDeliveryError("exception-secret-ambiguous"),
                Destination.Status.NEEDS_REVIEW,
                "전송됐는지 확인하지 못했어요. 채널에 도착했는지 직접 봐 주세요.",
            ),
        )
        for error, expected_status, safe_message in cases:
            with self.subTest(status=expected_status), patch(
                "accounts.views.send_to_destination",
                side_effect=error,
            ) as send:
                response = self.client.post(reverse("destination_test", args=[pk]), follow=True)
                send.assert_called_once()
                destination.refresh_from_db()
                self.assertEqual(destination.status, expected_status)
                self.assertIsNotNone(destination.last_tested_at)
                self.assertContains(response, safe_message)
                self.assertNotContains(response, str(error))
                self.assertNotContains(response, self.discord_url)
                self.assertNotContains(response, destination.encrypted_webhook_url)

    @patch("accounts.notifications._delivery_opener")
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PRIVATE_DNS)
    def test_stored_webhook_that_becomes_unsafe_fails_without_request(
        self,
        _resolver,
        opener_factory,
    ):
        destination = self.create_destination()
        pk = destination.pk

        response = self.client.post(reverse("destination_test", args=[pk]), follow=True)

        opener_factory.assert_not_called()
        destination.refresh_from_db()
        self.assertEqual(destination.status, Destination.Status.DEFINITELY_FAILED)
        self.assertIsNotNone(destination.last_tested_at)
        self.assertContains(response, "저장된 웹훅을 쓸 수 없어요.")
        self.assertNotContains(response, self.discord_url)
        self.assertNotContains(response, destination.encrypted_webhook_url)

    @override_settings(DEBUG=True)
    @patch("accounts.notifications._delivery_opener", return_value=UnexpectedOpener())
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_debug_error_page_redacts_sender_url_locals(
        self,
        _resolver,
        _opener_factory,
    ):
        destination = self.create_destination()
        pk = destination.pk
        self.client.raise_request_exception = False

        with self.assertLogs("django.request", level="ERROR"):
            response = self.client.post(reverse("destination_test", args=[pk]))

        self.assertEqual(response.status_code, 500)
        self.assertNotContains(response, self.discord_url, status_code=500)
        self.assertNotContains(
            response,
            destination.encrypted_webhook_url,
            status_code=500,
        )

    @patch("accounts.views.send_to_destination")
    def test_other_users_destination_is_never_tested_or_rendered(self, send):
        other = self.create_destination(self.other)
        pk = other.pk

        response = self.client.post(reverse("destination_test", args=[pk]), follow=True)

        send.assert_not_called()
        self.assertContains(response, "알림 대상을 먼저 추가해 주세요.")
        self.assertNotContains(response, self.discord_url)
        self.assertNotContains(response, other.encrypted_webhook_url)
