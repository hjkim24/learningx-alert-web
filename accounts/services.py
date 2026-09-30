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
from .schools import DEFAULT_SCHOOL, get_school, is_enabled, school_full


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
def verify_and_store_connection(*, user, token, school=None, client_class=CanvasClient):
    """Verify ``token`` against the chosen school's Canvas and store it.

    A user who is already connected keeps their school (a token swap); moving
    to another school means disconnecting first, so course ids from two
    Canvas instances never mix. Raises CanvasConnectionError with
    ``school_unavailable`` / ``school_full`` before any Canvas request.
    """
    normalized_token = token.strip()
    existing = CanvasConnection.objects.filter(user=user).values_list("school", flat=True).first()
    code = existing or school or DEFAULT_SCHOOL
    if existing is None:
        if not is_enabled(code):
            raise CanvasConnectionError("school_unavailable")
        if school_full(code):
            raise CanvasConnectionError("school_full")
    try:
        profile = client_class(get_school(code).canvas_base_url, normalized_token).profile()
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
                "school": code,
                "canvas_user_id": canvas_user_id,
                "canvas_name": canvas_name[:255],
                "encrypted_token": encrypt_secret(normalized_token),
                "verified_at": timezone.now(),
                "needs_reconnect": False,
            },
        )
    return connection
