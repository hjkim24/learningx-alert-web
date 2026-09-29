import json
import socket
from datetime import UTC, datetime
from urllib.error import HTTPError
from unittest.mock import patch

from django.test import SimpleTestCase

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.notifications import (
    AmbiguousDeliveryError,
    DefiniteDeliveryError,
    WebhookValidationError,
    render_notification,
    send_webhook_part,
    split_message,
    validate_webhook_url,
)
from tests.fakes import FakeOpener, FakeResponse


class RaisingOpener:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def open(self, request, timeout=30):
        self.calls += 1
        raise self.error


class NotificationTests(SimpleTestCase):
    def test_discord_requires_exact_host_path_and_no_user_query(self):
        valid = "https://discord.com/api/webhooks/123/abc_DEF-9"
        self.assertEqual(
            validate_webhook_url("discord", valid, resolve_public=False),
            valid,
        )
        for invalid in (
            "http://discord.com/api/webhooks/123/token",
            "https://evil.example/api/webhooks/123/token",
            "https://discord.com:443/api/webhooks/123/token",
            "https://discord.com:8443/api/webhooks/123/token",
            "https://discord.com/api/webhooks/123/token?wait=true",
            "https://discord.com/api/webhooks/123/token#fragment",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(
                WebhookValidationError
            ):
                validate_webhook_url("discord", invalid, resolve_public=False)

    def test_slack_requires_services_path_on_hooks_host(self):
        valid = "https://hooks.slack.com/services/T1/B2/secret"
        self.assertEqual(
            validate_webhook_url("slack", valid, resolve_public=False),
            valid,
        )
        with self.assertRaises(WebhookValidationError):
            validate_webhook_url(
                "slack",
                "https://slack.com/services/T1/B2/secret",
                resolve_public=False,
            )

    @patch(
        "learningx_alert.network.socket.getaddrinfo",
        return_value=[
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 443),
            )
        ],
    )
    def test_private_resolution_is_rejected_before_request(self, _resolver):
        with self.assertRaises(WebhookValidationError):
            validate_webhook_url(
                "slack",
                "https://hooks.slack.com/services/T/B/S",
            )

    def test_discord_success_requires_confirmation_id(self):
        opener = FakeOpener(
            [
                FakeResponse(
                    "https://discord.com/api/webhooks/123/token?wait=true",
                    b'{"id":"message-1"}',
                )
            ]
        )

        receipt = send_webhook_part(
            "discord",
            "https://discord.com/api/webhooks/123/token",
            "시험",
            opener=opener,
            resolve_public=False,
        )

        self.assertEqual(receipt, "message-1")
        payload = json.loads(opener.requests[0].data)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["content"], "시험")
        self.assertEqual(len(opener.requests), 1)

    def test_slack_success_requires_200_ok_body(self):
        opener = FakeOpener(
            [FakeResponse("https://hooks.slack.com/services/T/B/S", b"ok")]
        )

        receipt = send_webhook_part(
            "slack",
            "https://hooks.slack.com/services/T/B/S",
            "시험",
            opener=opener,
            resolve_public=False,
        )

        self.assertEqual(receipt, "ok")
        self.assertEqual(json.loads(opener.requests[0].data), {"text": "시험"})
        self.assertEqual(len(opener.requests), 1)

    def test_renderer_orders_items_and_includes_safe_failures(self):
        result = CollectionResult(
            (
                AlertItem(
                    101,
                    "회로",
                    "2",
                    "assignment",
                    "두 번째",
                    datetime(2026, 9, 28, tzinfo=UTC),
                    "unsubmitted",
                ),
                AlertItem(
                    101,
                    "회로",
                    "1",
                    "assignment",
                    "첫 번째",
                    datetime(2026, 9, 27, tzinfo=UTC),
                    "unsubmitted",
                ),
            ),
            (
                CourseOutcome(
                    202,
                    "재료",
                    "failed",
                    "assignments_failed",
                    "과제 목록을 확인하지 못했습니다.",
                ),
            ),
        )

        text = render_notification(result, datetime(2026, 9, 26, tzinfo=UTC))

        self.assertLess(text.index("첫 번째"), text.index("두 번째"))
        self.assertIn("조회 실패", text)
        self.assertIn("assignments_failed", text)

    def test_renderer_neutralizes_provider_mentions_from_external_titles(self):
        result = CollectionResult(
            (
                AlertItem(
                    101,
                    "@here 회로",
                    "1",
                    "assignment",
                    "@everyone <!channel>",
                    datetime(2026, 9, 27, tzinfo=UTC),
                    "unsubmitted",
                ),
            ),
            (),
        )

        text = render_notification(result, datetime(2026, 9, 26, tzinfo=UTC))

        self.assertNotIn("@here", text)
        self.assertNotIn("@everyone", text)
        self.assertNotIn("<!channel>", text)

    def test_split_message_preserves_text_and_utf16_limit(self):
        text = ("가" * 1899) + "😀" + ("나" * 100)

        parts = split_message(text)

        self.assertEqual("".join(parts), text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(
            all(len(part.encode("utf-16-le")) // 2 <= 1900 for part in parts)
        )

    def test_http_4xx_is_definite_and_timeout_is_ambiguous(self):
        discord_url = "https://discord.com/api/webhooks/123/token"
        definite = RaisingOpener(
            HTTPError(discord_url, 404, "Not Found", {}, None)
        )
        with self.assertRaises(DefiniteDeliveryError):
            send_webhook_part(
                "discord",
                discord_url,
                "시험",
                opener=definite,
                resolve_public=False,
            )
        self.assertEqual(definite.calls, 1)

        ambiguous = RaisingOpener(TimeoutError("network timeout"))
        with self.assertRaises(AmbiguousDeliveryError):
            send_webhook_part(
                "discord",
                discord_url,
                "시험",
                opener=ambiguous,
                resolve_public=False,
            )
        self.assertEqual(ambiguous.calls, 1)

    def test_invalid_success_confirmation_is_ambiguous_without_retry(self):
        opener = FakeOpener(
            [
                FakeResponse(
                    "https://discord.com/api/webhooks/123/token?wait=true",
                    b"{}",
                )
            ]
        )

        with self.assertRaises(AmbiguousDeliveryError):
            send_webhook_part(
                "discord",
                "https://discord.com/api/webhooks/123/token",
                "시험",
                opener=opener,
                resolve_public=False,
            )

        self.assertEqual(len(opener.requests), 1)


class GroupedMessageTests(SimpleTestCase):
    """Chat messages group items by KST due date, then by course."""

    def item(self, course_id, course, external_id, title, due, item_type="assignment"):
        return AlertItem(course_id, course, external_id, item_type, title, due, "unsubmitted")

    def test_items_are_grouped_by_day_then_course(self):
        now = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)  # 15:00 KST, Tuesday
        result = CollectionResult(
            (
                self.item(2, "디지털시스템_ICE3024_42(임완수)", "b", "week 5", datetime(2026, 9, 30, 14, 59, tzinfo=UTC), "lecture"),
                self.item(1, "전자회로_EEE2013_41(최병덕)", "a", "HW 3", datetime(2026, 9, 30, 5, 0, tzinfo=UTC)),
                self.item(1, "전자회로_EEE2013_41(최병덕)", "c", "HW 4", datetime(2026, 9, 30, 14, 59, tzinfo=UTC)),
                self.item(2, "디지털시스템_ICE3024_42(임완수)", "d", "week 6", datetime(2026, 10, 4, 14, 59, tzinfo=UTC), "lecture"),
            ),
            (),
        )

        text = render_notification(result, now)

        self.assertEqual(
            text.split("\n"),
            [
                "LearningX Alert · 2026.09.29 15:00 KST",
                "마감 4건",
                "",
                "■ 9월 30일 (수) · D-1",
                "전자회로",
                "- [과제] HW 3 · 14:00",
                "- [과제] HW 4 · 23:59",
                "디지털시스템",
                "- [강의] week 5 · 23:59",
                "",
                "■ 10월 4일 (일) · D-5",
                "디지털시스템",
                "- [강의] week 6 · 23:59",
            ],
        )

    def test_day_uses_kst_not_utc_and_today_label(self):
        now = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)  # 09:00 KST
        result = CollectionResult(
            (self.item(1, "회로", "a", "오늘 과제", datetime(2026, 9, 29, 14, 30, tzinfo=UTC)),),  # 23:30 KST
            (),
        )

        text = render_notification(result, now)

        self.assertIn("■ 9월 29일 (화) · 오늘", text)
        self.assertIn("- [과제] 오늘 과제 · 23:30", text)

    def test_same_title_in_two_sections_stays_separate(self):
        now = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)
        due = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
        result = CollectionResult(
            (
                self.item(1, "글로벌캡스톤디자인_ERC3001_42(임완수)", "a", "보고서", due),
                self.item(2, "글로벌캡스톤디자인_ERC3001_42(임완수)", "b", "보고서", due),
            ),
            (),
        )

        text = render_notification(result, now)

        self.assertEqual(text.count("글로벌캡스톤디자인\n"), 2)

    def test_course_names_and_titles_are_still_sanitized(self):
        now = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)
        result = CollectionResult(
            (self.item(1, "@here 회로", "a", "@everyone <!channel>", datetime(2026, 9, 30, tzinfo=UTC)),),
            (),
        )

        text = render_notification(result, now)

        self.assertNotIn("@here", text)
        self.assertNotIn("@everyone", text)
        self.assertNotIn("<!channel>", text)
