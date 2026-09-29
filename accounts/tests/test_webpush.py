import json
import socket
from datetime import UTC, datetime, timedelta
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import webpush
from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.tests.helpers import make_rule
from accounts.models import Delivery, Destination, NotificationRule, ScheduledRun
from accounts.notifications import (
    AmbiguousDeliveryError,
    DefiniteDeliveryError,
    SubscriptionGoneError,
    message_parts,
    save_push_subscription,
    send_web_push,
)
from accounts.scheduling import claim_due_runs, execute_run
from accounts.services import decrypt_secret, encrypt_secret


KEY = Fernet.generate_key().decode()
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]
PRIVATE_DNS = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 443))]
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-token-1"


def browser_subscription(endpoint=ENDPOINT):
    """A subscription as a browser would produce it, with its private key."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return (
        {
            "endpoint": endpoint,
            "keys": {"p256dh": webpush.b64url_encode(public), "auth": webpush.b64url_encode(b"a" * 16)},
        },
        private,
    )


class RFC8291VectorTests(TestCase):
    """RFC 8291 section 5 / appendix A worked example, byte for byte."""

    def test_encryption_matches_rfc_example(self):
        sender = ec.derive_private_key(
            int.from_bytes(webpush.b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
            ec.SECP256R1(),
        )
        body = webpush.encrypt_payload(
            b"When I grow up, I want to be a watermelon",
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
            "BTBZMqHH6r4Tts7J_aSIgg",
            sender_private_key=sender,
            salt=webpush.b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
        )
        expected = webpush.b64url_decode(
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
            "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
            "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
        )
        self.assertEqual(body, expected)

    def test_oversized_payload_is_refused(self):
        subscription, _ = browser_subscription()
        with self.assertRaises(ValueError):
            webpush.encrypt_payload(
                b"x" * (webpush.MAX_PLAINTEXT_BYTES + 1),
                subscription["keys"]["p256dh"],
                subscription["keys"]["auth"],
            )

    def test_push_payload_is_trimmed_to_one_record(self):
        payload = webpush.push_payload("title", "가" * 5000)
        self.assertLessEqual(len(payload), webpush.MAX_PLAINTEXT_BYTES)
        self.assertEqual(json.loads(payload)["title"], "title")


class SubscriptionValidationTests(TestCase):
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_known_push_services_are_accepted(self, _dns):
        for endpoint in (
            ENDPOINT,
            "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "https://web.push.apple.com/QPdE",
            "https://wns2-par02p.notify.windows.com/w/?token=abc",
            "https://jmt17.google.com/fcm/send/abc:APA91b",
        ):
            with self.subTest(endpoint=endpoint):
                subscription, _ = browser_subscription(endpoint)
                self.assertEqual(webpush.normalize_subscription(subscription)["endpoint"], endpoint)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_unknown_hosts_and_bad_urls_are_rejected(self, _dns):
        for endpoint in (
            "https://evil.example.com/push",
            "http://fcm.googleapis.com/fcm/send/x",
            "https://fcm.googleapis.com:8443/fcm/send/x",
            "https://user:pw@fcm.googleapis.com/fcm/send/x",
            "https://fcm.googleapis.com.evil.com/x",
            "https://jmt17.google.com.evil.com/x",
            "https://evil-jmt17.google.com/x",
            "https://jmtx.google.com/x",
            "https://google.com/fcm/send/x",
        ):
            with self.subTest(endpoint=endpoint):
                subscription, _ = browser_subscription(endpoint)
                with self.assertRaises(webpush.PushValidationError):
                    webpush.normalize_subscription(subscription)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PRIVATE_DNS)
    def test_push_host_resolving_to_private_address_is_rejected(self, _dns):
        subscription, _ = browser_subscription()
        with self.assertRaises(webpush.PushValidationError):
            webpush.normalize_subscription(subscription)

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_bad_keys_are_rejected(self, _dns):
        subscription, _ = browser_subscription()
        cases = (
            {**subscription, "keys": {**subscription["keys"], "p256dh": webpush.b64url_encode(b"\x04" + b"\x01" * 64)}},
            {**subscription, "keys": {**subscription["keys"], "auth": webpush.b64url_encode(b"short")}},
            {"endpoint": ENDPOINT},
            "not-a-dict",
        )
        for case in cases:
            with self.subTest(case=str(case)[:40]), self.assertRaises(webpush.PushValidationError):
                webpush.normalize_subscription(case)


class VapidTests(TestCase):
    @override_settings(WEB_PUSH_SUBJECT="https://alert.example.com")
    def test_token_is_a_valid_es256_jwt_for_the_push_origin(self):
        header_value = webpush.vapid_authorization(ENDPOINT, now=1_700_000_000)
        token = header_value.split("t=", 1)[1].split(",", 1)[0]
        public_key = header_value.split("k=", 1)[1]
        head, claims, signature = token.split(".")

        self.assertEqual(json.loads(webpush.b64url_decode(head)), {"typ": "JWT", "alg": "ES256"})
        payload = json.loads(webpush.b64url_decode(claims))
        self.assertEqual(payload["aud"], "https://fcm.googleapis.com")
        self.assertEqual(payload["sub"], "https://alert.example.com")
        self.assertEqual(payload["exp"], 1_700_000_000 + webpush.VAPID_TOKEN_SECONDS)

        raw = webpush.b64url_decode(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        verifier = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), webpush.b64url_decode(public_key)
        )
        verifier.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):
            verifier.verify(der, f"{head}.tampered".encode(), ec.ECDSA(hashes.SHA256()))

    def test_derived_key_is_stable_and_follows_secret_key(self):
        first = webpush.vapid_public_key()
        self.assertEqual(first, webpush.vapid_public_key())
        with override_settings(SECRET_KEY="another-secret"):
            self.assertNotEqual(first, webpush.vapid_public_key())

    def test_explicit_private_key_overrides_derivation(self):
        scalar = webpush.b64url_encode((12345).to_bytes(32, "big"))
        with override_settings(WEB_PUSH_VAPID_PRIVATE_KEY=scalar):
            expected = ec.derive_private_key(12345, ec.SECP256R1()).public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            )
            self.assertEqual(webpush.vapid_public_key(), webpush.b64url_encode(expected))


class FakeResponse:
    def __init__(self, status=201, location="https://fcm.googleapis.com/m/msg-42"):
        self.status = status
        self.headers = Message()
        if location:
            self.headers["Location"] = location

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RecordingOpener:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.requests = []

    def open(self, request, timeout=30):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class SendWebPushTests(TestCase):
    def setUp(self):
        subscription, self.browser_key = browser_subscription()
        self.subscription_json = json.dumps(subscription)

    def http_error(self, code):
        return HTTPError(ENDPOINT, code, "error", Message(), None)

    def test_request_is_encrypted_and_authorized(self):
        opener = RecordingOpener()

        receipt = send_web_push(self.subscription_json, '{"title":"t"}', opener=opener, resolve_public=False)

        self.assertEqual(receipt, "msg-42")
        request = opener.requests[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-encoding"), "aes128gcm")
        self.assertEqual(request.get_header("Ttl"), str(webpush.PUSH_TTL_SECONDS))
        self.assertTrue(request.get_header("Authorization").startswith("vapid t="))
        self.assertNotIn(b'"title"', request.data)
        self.assertEqual(request.data[16:20], webpush.RECORD_SIZE.to_bytes(4, "big"))

    def test_gone_subscription_is_reported(self):
        for code in (404, 410):
            with self.subTest(code=code), self.assertRaises(SubscriptionGoneError):
                send_web_push(
                    self.subscription_json,
                    "{}",
                    opener=RecordingOpener(error=self.http_error(code)),
                    resolve_public=False,
                )

    def test_other_rejections_are_definite_and_network_errors_ambiguous(self):
        with self.assertRaises(DefiniteDeliveryError):
            send_web_push(
                self.subscription_json,
                "{}",
                opener=RecordingOpener(error=self.http_error(403)),
                resolve_public=False,
            )
        with self.assertRaises(AmbiguousDeliveryError):
            send_web_push(
                self.subscription_json,
                "{}",
                opener=RecordingOpener(error=URLError("timeout")),
                resolve_public=False,
            )

    def test_stored_subscription_to_foreign_host_is_never_requested(self):
        subscription, _ = browser_subscription("https://evil.example.com/push")
        opener = RecordingOpener()
        with self.assertRaises(DefiniteDeliveryError):
            send_web_push(json.dumps(subscription), "{}", opener=opener, resolve_public=False)
        self.assertEqual(opener.requests, [])


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
@patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
class PushSubscriptionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)
        self.subscription, _ = browser_subscription()

    def subscribe(self, subscription=None, label="macOS Chrome", client=None):
        return (client or self.client).post(
            reverse("push_subscribe"),
            data=json.dumps({"subscription": subscription or self.subscription, "label": label}),
            content_type="application/json",
        )

    def test_subscribe_stores_encrypted_subscription(self, _dns):
        response = self.subscribe()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["created"])
        destination = Destination.objects.get(user=self.user)
        self.assertEqual(destination.kind, Destination.Kind.WEBPUSH)
        self.assertEqual(destination.label, "macOS Chrome")
        self.assertNotIn(ENDPOINT, destination.encrypted_webhook_url)
        self.assertEqual(json.loads(decrypt_secret(destination.encrypted_webhook_url))["endpoint"], ENDPOINT)

    def test_resubscribing_same_browser_refreshes_instead_of_duplicating(self, _dns):
        self.subscribe()
        renewed, _ = browser_subscription()

        response = self.subscribe(renewed)

        self.assertFalse(response.json()["created"])
        destination = Destination.objects.get(user=self.user)
        self.assertEqual(
            json.loads(decrypt_secret(destination.encrypted_webhook_url))["keys"],
            renewed["keys"],
        )

    def test_silent_resync_of_existing_browser_shows_no_message(self, _dns):
        self.subscribe()
        self.client.get(reverse("destination_settings"))  # consume the "added" flash

        response = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"subscription": self.subscription, "label": "macOS Chrome", "silent": True}),
            content_type="application/json",
        )
        page = self.client.get(reverse("destination_settings"))

        self.assertFalse(response.json()["created"])
        self.assertNotContains(page, "푸시 등록을 갱신했어요")
        self.assertEqual(Destination.objects.filter(user=self.user).count(), 1)

    def test_silent_resync_recreates_a_deleted_destination(self, _dns):
        self.subscribe()
        Destination.objects.filter(user=self.user).delete()

        response = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"subscription": self.subscription, "silent": True}),
            content_type="application/json",
        )

        self.assertTrue(response.json()["created"])
        self.assertEqual(Destination.objects.filter(user=self.user).count(), 1)

    def test_chrome_jmt_endpoint_registers(self, _dns):
        subscription, _ = browser_subscription("https://jmt17.google.com/fcm/send/abc:APA91b")

        response = self.subscribe(subscription)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Destination.objects.filter(user=self.user, kind="webpush").exists())

    def test_invalid_subscription_is_rejected(self, _dns):
        bad, _ = browser_subscription("https://evil.example.com/push")
        self.assertEqual(self.subscribe(bad).status_code, 400)
        response = self.client.post(reverse("push_subscribe"), data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Destination.objects.exists())

    def test_subscribe_requires_csrf_login_and_post(self, _dns):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(self.subscribe(client=csrf_client).status_code, 403)
        self.assertEqual(self.client.get(reverse("push_subscribe")).status_code, 405)
        anonymous = self.subscribe(client=Client())
        self.assertEqual(anonymous.status_code, 302)
        self.assertFalse(Destination.objects.exists())

    @override_settings(WEB_PUSH_ENABLED=False)
    def test_disabled_push_refuses_and_hides_panel(self, _dns):
        self.assertEqual(self.subscribe().status_code, 404)
        page = self.client.get(reverse("destination_settings"))
        self.assertNotContains(page, "data-push")

    def test_unsubscribe_removes_only_matching_browser(self, _dns):
        self.subscribe()
        other, _ = browser_subscription("https://fcm.googleapis.com/fcm/send/other")
        self.subscribe(other, label="Android Chrome")

        response = self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": ENDPOINT}),
            content_type="application/json",
        )

        self.assertTrue(response.json()["deleted"])
        self.assertEqual(
            list(Destination.objects.filter(user=self.user).values_list("label", flat=True)),
            ["Android Chrome"],
        )

    def test_settings_page_lists_every_destination_without_secrets(self, _dns):
        self.subscribe()
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            label="과제 채널",
            encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/secret"),
        )

        page = self.client.get(reverse("destination_settings"))

        self.assertContains(page, "macOS Chrome")
        self.assertContains(page, "과제 채널")
        self.assertContains(page, webpush.vapid_public_key())
        self.assertNotContains(page, ENDPOINT)
        self.assertNotContains(page, "webhooks/1/secret")

    def test_push_test_send_on_gone_subscription_removes_it(self, _dns):
        self.subscribe()
        destination = Destination.objects.get(user=self.user)
        with patch("accounts.views.send_to_destination", side_effect=SubscriptionGoneError("gone")):
            response = self.client.post(reverse("destination_test", args=[destination.pk]), follow=True)
        self.assertContains(response, "푸시 등록이 만료돼서 삭제했어요")
        self.assertFalse(Destination.objects.filter(pk=destination.pk).exists())


class PwaFileTests(TestCase):
    def test_service_worker_is_root_scoped_and_public(self):
        response = Client().get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("text/javascript", response["Content-Type"])
        self.assertIn("showNotification", response.content.decode())

    def test_manifest_is_installable(self):
        response = Client().get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual({icon["sizes"] for icon in data["icons"]}, {"192x192", "512x512"})

    def test_icon_files_exist_and_favicon_redirects(self):
        from django.conf import settings

        icons = settings.BASE_DIR / "static" / "icons"
        for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png", "favicon.ico", "favicon.svg"):
            self.assertTrue((icons / name).is_file(), name)
        response = Client().get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("icons/favicon.ico"))
        page = Client().get("/accounts/login/").content.decode()
        self.assertIn("icons/favicon.svg", page)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class MultiDestinationRunTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.discord = self.add(Destination.Kind.DISCORD, "https://discord.com/api/webhooks/1/a", "디스코드")
        self.slack = self.add(Destination.Kind.SLACK, "https://hooks.slack.com/services/T/B/c", "슬랙")
        subscription, _ = browser_subscription()
        self.push = self.add(Destination.Kind.WEBPUSH, json.dumps(subscription), "macOS Chrome")
        self.result = CollectionResult(
            (AlertItem(101, "전자회로", "55", "assignment", "HW", self.now + timedelta(days=1), "unsubmitted"),),
            (CourseOutcome(101, "전자회로", "success"),),
        )
        self.run = ScheduledRun.objects.create(user=self.user, scheduled_for=self.now)
        self.calls = []

    def add(self, kind, secret, label):
        return Destination.objects.create(
            user=self.user, kind=kind, label=label, encrypted_webhook_url=encrypt_secret(secret)
        )

    def execute(self, sender):
        return execute_run(self.run, self.now, collector=lambda user, now: self.result, sender=sender)

    def test_every_destination_receives_the_run(self):
        def sender(kind, secret, part):
            self.calls.append((kind, secret, part))
            return f"receipt-{kind}"

        run = self.execute(sender)

        self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)
        self.assertEqual([call[0] for call in self.calls], ["discord", "slack", "webpush"])
        push_payload = json.loads(self.calls[2][2])
        self.assertIn("마감 알림 1건", push_payload["title"])
        self.assertIn("HW", push_payload["body"])
        self.assertIn("전자회로\n- [과제] HW ·", self.calls[0][2])
        deliveries = list(Delivery.objects.filter(run=run))
        self.assertEqual(len(deliveries), 3)
        self.assertEqual({d.destination_label for d in deliveries}, {"디스코드", "슬랙", "macOS Chrome"})
        self.assertEqual(len({d.idempotency_key for d in deliveries}), 3)

    def test_one_failure_does_not_stop_the_others(self):
        def sender(kind, _secret, _part):
            self.calls.append(kind)
            if kind == "discord":
                raise DefiniteDeliveryError("rejected")
            return "ok"

        run = self.execute(sender)

        self.assertEqual(self.calls, ["discord", "slack", "webpush"])
        self.assertEqual(run.status, ScheduledRun.Status.FAILED)
        self.assertEqual(run.safe_error_code, "delivery_definite")
        statuses = dict(Delivery.objects.filter(run=run).values_list("destination_kind", "status"))
        self.assertEqual(
            statuses,
            {
                "discord": Delivery.Status.DEFINITELY_FAILED,
                "slack": Delivery.Status.SUCCEEDED,
                "webpush": Delivery.Status.SUCCEEDED,
            },
        )

    def test_ambiguous_outcome_takes_precedence_for_review(self):
        def sender(kind, _secret, _part):
            if kind == "discord":
                raise DefiniteDeliveryError("rejected")
            if kind == "slack":
                raise AmbiguousDeliveryError("timeout")
            return "ok"

        run = self.execute(sender)

        self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
        self.assertEqual(run.safe_error_code, "delivery_ambiguous")

    def test_gone_push_subscription_is_removed(self):
        def sender(kind, _secret, _part):
            if kind == "webpush":
                raise SubscriptionGoneError("gone")
            return "ok"

        run = self.execute(sender)

        self.assertEqual(run.status, ScheduledRun.Status.FAILED)
        self.assertEqual(run.safe_error_code, "push_subscription_gone")
        self.assertFalse(Destination.objects.filter(pk=self.push.pk).exists())
        delivery = Delivery.objects.get(run=run, destination_kind="webpush")
        self.assertIsNone(delivery.destination_id)
        self.assertEqual(delivery.destination_label, "macOS Chrome")
        self.assertEqual(delivery.safe_error_code, "push_subscription_gone")

    def test_long_message_splits_for_chat_but_stays_one_push(self):
        long_result = CollectionResult(
            (AlertItem(101, "전자회로", "55", "assignment", "가" * 4000, self.now + timedelta(days=1), "x"),),
            (CourseOutcome(101, "전자회로", "success"),),
        )
        self.assertGreater(len(message_parts(Destination.Kind.DISCORD, long_result, self.now)), 1)
        parts = message_parts(Destination.Kind.WEBPUSH, long_result, self.now)
        self.assertEqual(len(parts), 1)
        self.assertLessEqual(len(parts[0].encode()), webpush.MAX_PLAINTEXT_BYTES)

    def test_push_only_user_is_scheduled(self):
        Destination.objects.filter(pk__in=(self.discord.pk, self.slack.pk)).delete()
        self.user.course_selections.create(
            canvas_course_id=101, course_name="전자회로", enabled=True, include_assignments=True
        )
        from accounts.models import CanvasConnection

        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token=encrypt_secret("token"),
            verified_at=self.now,
        )
        make_rule(self.user, datetime(2026, 1, 1, 9, 0).time())
        ScheduledRun.objects.all().delete()

        claimed = claim_due_runs(self.now)

        self.assertEqual(len(claimed), 1)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class PushHelperTests(TestCase):
    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_other_users_cannot_share_fingerprints(self, _dns):
        first = get_user_model().objects.create_user(username="a@example.com")
        second = get_user_model().objects.create_user(username="b@example.com")
        subscription, _ = browser_subscription()

        save_push_subscription(first, subscription)
        save_push_subscription(second, subscription)

        self.assertEqual(Destination.objects.count(), 2)
