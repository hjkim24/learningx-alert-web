import json
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from learningx_alert.canvas import CanvasClient

from .models import CanvasConnection


class CanvasConnectionError(Exception):
    pass


def _fernet():
    try:
        return MultiFernet(
            [Fernet(key.encode()) for key in settings.CREDENTIAL_ENCRYPTION_KEYS]
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            "CREDENTIAL_ENCRYPTION_KEYS must contain valid Fernet keys"
        ) from exc


def encrypt_secret(value):
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    return _fernet().decrypt(value.encode()).decode()


@sensitive_variables("token", "normalized_token")
def verify_and_store_connection(*, user, token, client_class=CanvasClient):
    normalized_token = token.strip()
    try:
        profile = client_class(settings.CANVAS_BASE_URL, normalized_token).profile()
        canvas_user_id = str(profile.id)
        canvas_name = str(profile.name)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise CanvasConnectionError("canvas_verification_failed") from exc

    with transaction.atomic():
        connection, _ = CanvasConnection.objects.update_or_create(
            user=user,
            defaults={
                "canvas_user_id": canvas_user_id,
                "canvas_name": canvas_name,
                "encrypted_token": encrypt_secret(normalized_token),
                "verified_at": timezone.now(),
            },
        )
    return connection
