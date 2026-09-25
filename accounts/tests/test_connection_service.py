from urllib.error import URLError

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from accounts.models import CanvasConnection
from accounts.services import (
    CanvasConnectionError,
    decrypt_secret,
    encrypt_secret,
    verify_and_store_connection,
)
from learningx_alert.models import CanvasProfile


KEY = Fernet.generate_key().decode()


class FakeCanvasClient:
    def __init__(self, base_url, token):
        self.token = token

    def profile(self):
        if self.token == "invalid":
            raise URLError("upstream detail containing invalid")
        return CanvasProfile(id=1234, name="김학재")


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class CanvasConnectionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")

    def test_round_trip_is_encrypted(self):
        ciphertext = encrypt_secret("token value")

        self.assertNotIn("token value", ciphertext)
        self.assertEqual(decrypt_secret(ciphertext), "token value")

    def test_old_ciphertext_survives_ordered_key_rotation(self):
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        with self.settings(CREDENTIAL_ENCRYPTION_KEYS=[old_key]):
            ciphertext = encrypt_secret("rotating token")

        with self.settings(CREDENTIAL_ENCRYPTION_KEYS=[new_key, old_key]):
            self.assertEqual(decrypt_secret(ciphertext), "rotating token")

    def test_missing_key_fails_without_exposing_configuration(self):
        with self.settings(CREDENTIAL_ENCRYPTION_KEYS=[]):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "CREDENTIAL_ENCRYPTION_KEYS must contain valid Fernet keys",
            ):
                encrypt_secret("secret")

    def test_valid_token_creates_one_connection(self):
        connection = verify_and_store_connection(
            user=self.user,
            token="  good token  ",
            client_class=FakeCanvasClient,
        )

        self.assertEqual(connection.canvas_user_id, "1234")
        self.assertEqual(connection.canvas_name, "김학재")
        self.assertEqual(decrypt_secret(connection.encrypted_token), "good token")

    def test_invalid_token_is_not_stored(self):
        with self.assertRaisesMessage(
            CanvasConnectionError,
            "canvas_verification_failed",
        ):
            verify_and_store_connection(
                user=self.user,
                token="invalid",
                client_class=FakeCanvasClient,
            )

        self.assertFalse(CanvasConnection.objects.exists())

    def test_invalid_replacement_keeps_previous_ciphertext(self):
        existing = verify_and_store_connection(
            user=self.user,
            token="good",
            client_class=FakeCanvasClient,
        )

        with self.assertRaisesMessage(
            CanvasConnectionError,
            "canvas_verification_failed",
        ):
            verify_and_store_connection(
                user=self.user,
                token="invalid",
                client_class=FakeCanvasClient,
            )

        existing.refresh_from_db()
        self.assertEqual(decrypt_secret(existing.encrypted_token), "good")
        self.assertEqual(CanvasConnection.objects.count(), 1)
