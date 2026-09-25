from urllib.error import URLError
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CanvasConnection
from accounts.services import decrypt_secret, encrypt_secret
from learningx_alert.canvas import CanvasClient
from learningx_alert.models import CanvasProfile


KEY = Fernet.generate_key().decode()


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class CanvasConnectionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")

    def create_connection(self, user, *, token="stored", canvas_user_id="1"):
        return CanvasConnection.objects.create(
            user=user,
            canvas_user_id=canvas_user_id,
            canvas_name=f"Canvas {canvas_user_id}",
            encrypted_token=encrypt_secret(token),
            verified_at=timezone.now(),
        )

    def test_connect_requires_login(self):
        response = self.client.post(reverse("canvas_connect"), {"token": "secret"})

        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("canvas_connect")}',
        )

    def test_connect_rejects_get(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("canvas_connect")).status_code, 405)

    @patch.object(CanvasClient, "profile", return_value=CanvasProfile(1234, "김학재"))
    @patch.object(CanvasClient, "__init__", return_value=None)
    def test_connect_stores_only_current_users_encrypted_token(self, _init, _profile):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("canvas_connect"),
            {"token": " secret-value "},
            follow=True,
        )

        self.assertRedirects(response, reverse("dashboard"))
        connection = CanvasConnection.objects.get(user=self.user)
        self.assertEqual(decrypt_secret(connection.encrypted_token), "secret-value")
        self.assertNotEqual(connection.encrypted_token, "secret-value")
        self.assertFalse(CanvasConnection.objects.filter(user=self.other).exists())
        self.assertNotContains(response, "secret-value")

    @patch.object(
        CanvasClient,
        "profile",
        side_effect=URLError("submitted-secret-must-not-appear"),
    )
    @patch.object(CanvasClient, "__init__", return_value=None)
    def test_invalid_token_shows_safe_error_without_storage(self, _init, _profile):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("canvas_connect"),
            {"token": "submitted-secret-must-not-appear"},
            follow=True,
        )

        self.assertContains(
            response,
            "Canvas 연결을 확인하지 못했습니다. 토큰을 다시 확인해 주세요.",
        )
        self.assertNotContains(response, "submitted-secret-must-not-appear")
        self.assertFalse(CanvasConnection.objects.exists())

    def test_connect_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get(reverse("dashboard"))

        response = client.post(reverse("canvas_connect"), {"token": "secret"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(CanvasConnection.objects.exists())

    def test_disconnect_deletes_only_current_users_connection(self):
        self.create_connection(self.user)
        other_connection = self.create_connection(
            self.other,
            canvas_user_id="2",
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("canvas_disconnect"))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(CanvasConnection.objects.filter(user=self.user).exists())
        self.assertTrue(CanvasConnection.objects.filter(pk=other_connection.pk).exists())

    def test_disconnect_rejects_get(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("canvas_disconnect")).status_code, 405)
