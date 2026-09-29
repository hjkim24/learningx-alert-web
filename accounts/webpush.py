"""Web Push delivery: RFC 8291 payload encryption and RFC 8292 VAPID.

Implemented on `cryptography` and the project's pinned HTTPS opener instead of
a third-party client, so a browser-supplied push endpoint goes through the same
public-address and host allowlist checks as Discord/Slack webhooks.
"""

import base64
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from learningx_alert.network import UnsafeUrlError, validate_https_url

# Push services run by the browser vendors. Anything else is refused, so a
# forged subscription cannot turn the scheduler into a request proxy.
PUSH_HOSTS = frozenset(
    {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
PUSH_HOST_SUFFIXES = (".notify.windows.com", ".push.apple.com")
# Stable Chrome now hands out endpoints on jmt<N>.google.com instead of
# fcm.googleapis.com; both are Google's push service.
PUSH_HOST_PATTERNS = (re.compile(r"jmt[0-9]{1,3}\.google\.com"),)
MAX_ENDPOINT_LENGTH = 2048
# RFC 8291 section 4: 4096-byte body minus the 86-byte header, delimiter and tag.
MAX_PLAINTEXT_BYTES = 3993
RECORD_SIZE = 4096
PUSH_TTL_SECONDS = 12 * 60 * 60
VAPID_TOKEN_SECONDS = 12 * 60 * 60
P256_ORDER = int(
    "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16
)


class PushValidationError(Exception):
    pass


def b64url_encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def b64url_decode(value):
    text = str(value).strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def is_push_host(host):
    host = (host or "").lower()
    return (
        host in PUSH_HOSTS
        or any(host.endswith(suffix) for suffix in PUSH_HOST_SUFFIXES)
        or any(pattern.fullmatch(host) for pattern in PUSH_HOST_PATTERNS)
    )


@sensitive_variables()
def validate_push_endpoint(endpoint, resolve_public=True):
    endpoint = str(endpoint or "").strip()
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        if (
            len(endpoint) > MAX_ENDPOINT_LENGTH
            or not is_push_host(host)
            or parsed.port is not None
            or parsed.fragment
        ):
            raise PushValidationError("push_endpoint_invalid")
        validate_https_url(endpoint, {host}, resolve_public=resolve_public)
    except (TypeError, ValueError, UnsafeUrlError):
        raise PushValidationError("push_endpoint_invalid") from None
    return endpoint


def _load_public_key(raw):
    if len(raw) != 65 or raw[0] != 4:
        raise PushValidationError("push_key_invalid")
    try:
        # from_encoded_point verifies the point is on P-256 (RFC 8291 section 7).
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise PushValidationError("push_key_invalid") from None


@sensitive_variables()
def normalize_subscription(data, resolve_public=True):
    """Validate a browser PushSubscription JSON and return the stored form."""
    try:
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh = b64url_decode(keys["p256dh"])
        auth = b64url_decode(keys["auth"])
    except (KeyError, TypeError, ValueError):
        raise PushValidationError("push_subscription_invalid") from None
    endpoint = validate_push_endpoint(endpoint, resolve_public=resolve_public)
    _load_public_key(p256dh)
    if len(auth) != 16:
        raise PushValidationError("push_key_invalid")
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": b64url_encode(p256dh), "auth": b64url_encode(auth)},
    }


def endpoint_fingerprint(endpoint):
    return hashlib.sha256(endpoint.encode()).hexdigest()


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


@sensitive_variables()
def encrypt_payload(plaintext, p256dh, auth, *, sender_private_key=None, salt=None):
    """Encrypt one aes128gcm record for a subscription (RFC 8291 section 3.4)."""
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise ValueError("push payload too large")
    ua_public_raw = b64url_decode(p256dh)
    ua_public = _load_public_key(ua_public_raw)
    auth_secret = b64url_decode(auth)
    salt = salt or os.urandom(16)
    as_private = sender_private_key or ec.generate_private_key(ec.SECP256R1())
    as_public_raw = as_private.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )

    ecdh_secret = as_private.exchange(ec.ECDH(), ua_public)
    key_info = b"WebPush: info\x00" + ua_public_raw + as_public_raw
    ikm = _hkdf(auth_secret, ecdh_secret, key_info, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)

    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = (
        salt
        + RECORD_SIZE.to_bytes(4, "big")
        + bytes([len(as_public_raw)])
        + as_public_raw
    )
    return header + ciphertext


def vapid_private_key():
    """The server's VAPID key.

    `WEB_PUSH_VAPID_PRIVATE_KEY` (base64url raw scalar) wins when set; otherwise
    the key is derived from SECRET_KEY, so production needs no extra secret.
    Rotating SECRET_KEY therefore invalidates every browser subscription.
    """
    configured = getattr(settings, "WEB_PUSH_VAPID_PRIVATE_KEY", "")
    if configured:
        scalar = int.from_bytes(b64url_decode(configured), "big")
    else:
        seed = _hkdf(
            b"learningx-alert",
            settings.SECRET_KEY.encode(),
            b"web-push vapid key v1",
            48,
        )
        scalar = int.from_bytes(seed, "big") % (P256_ORDER - 1) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def vapid_public_key():
    raw = vapid_private_key().public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    return b64url_encode(raw)


def web_push_enabled():
    return bool(getattr(settings, "WEB_PUSH_ENABLED", False))


def vapid_authorization(endpoint, now=None):
    parsed = urlsplit(endpoint)
    audience = f"{parsed.scheme}://{parsed.hostname}"
    issued = int(now if now is not None else time.time())
    header = b64url_encode(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64url_encode(
        json.dumps(
            {
                "aud": audience,
                "exp": issued + VAPID_TOKEN_SECONDS,
                "sub": settings.WEB_PUSH_SUBJECT,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode()
    der = vapid_private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{signature}, k={vapid_public_key()}"


def push_payload(title, body, url="/"):
    """JSON the service worker renders, trimmed to fit one push record."""
    body = str(body)
    while True:
        payload = json.dumps(
            {"title": title, "body": body, "url": url},
            ensure_ascii=False,
        ).encode()
        if len(payload) <= MAX_PLAINTEXT_BYTES:
            return payload
        body = body[: max(0, len(body) - 200)].rstrip() + "…"
