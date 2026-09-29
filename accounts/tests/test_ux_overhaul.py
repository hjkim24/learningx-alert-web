from datetime import UTC, datetime, time
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.tests.helpers import alarm_post_data, make_rule
from accounts.models import CanvasConnection, CourseSelection, Destination, NotificationRule
from accounts.services import decrypt_secret, encrypt_secret
from accounts.templatetags.course_names import split_course_name
from accounts.tests.test_destination_views import PUBLIC_DNS
from accounts.views import _group_items_by_day


KEY = Fernet.generate_key().decode()
DISCORD_URL = "https://discord.com/api/webhooks/123/secret-token"


class CourseNameTests(SimpleTestCase):
    def test_splits_skku_course_names(self):
        cases = {
            "디지털시스템_ICE3024_42(임완수)": ("디지털시스템", "ICE3024", "42", "임완수"),
            "Advanced Materials Design(CapstoneDesign)_EAM3098_41(조형균)": (
                "Advanced Materials Design(CapstoneDesign)",
                "EAM3098",
                "41",
                "조형균",
            ),
            "안전교육_SFE7262_I1": ("안전교육", "SFE7262", "I1", ""),
            "Electromagnetism I _EEE2009_45(미트라게게르치)": (
                "Electromagnetism I",
                "EEE2009",
                "45",
                "미트라게게르치",
            ),
        }
        for raw, (title, code, section, professor) in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    split_course_name(raw),
                    {"title": title, "code": code, "section": section, "professor": professor},
                )

    def test_unknown_shapes_keep_raw_name(self):
        for raw in ("2021 자살예방교육 (보고듣고말하기)", "미래차 부트캠프 중급", ""):
            with self.subTest(raw=raw):
                self.assertEqual(split_course_name(raw)["title"], raw)
                self.assertEqual(split_course_name(raw)["code"], "")


class PreviewGroupingTests(SimpleTestCase):
    def item(self, title, due_at, item_type="assignment"):
        return AlertItem(1, "과목_ABC1234_41(교수)", title, item_type, title, due_at, "")

    def test_groups_by_kst_day_with_dday_labels(self):
        now = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # 12:00 KST
        items = (
            self.item("b", datetime(2026, 10, 4, 14, 59, tzinfo=UTC)),  # 10-04 23:59 KST
            self.item("a", datetime(2026, 9, 29, 14, 0, tzinfo=UTC)),  # 09-29 23:00 KST
            self.item("c", datetime(2026, 10, 4, 15, 1, tzinfo=UTC)),  # 10-05 00:01 KST
        )

        groups = _group_items_by_day(items, now)

        self.assertEqual([g["dday"] for g in groups], ["오늘", "D-5", "D-6"])
        self.assertEqual([g["urgent"] for g in groups], [True, False, False])
        self.assertEqual([[i.title for i in g["items"]] for g in groups], [["a"], ["b"], ["c"]])


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class NotificationSettingsSaveTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)
        self.url = reverse("notification_settings_save")

    def post(self, **overrides):
        data = {
            "lookahead_days": "7",
            **alarm_post_data("09:00"),
            "kind": Destination.Kind.DISCORD,
            "webhook_url": "",
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_rule_only_save_warns_that_destination_is_missing(self):
        response = self.client.post(
            self.url,
            {"lookahead_days": "7", **alarm_post_data("09:00"), "kind": "discord", "webhook_url": ""},
            follow=True,
        )

        self.assertRedirects(response, reverse("notification_settings"))
        self.assertEqual(NotificationRule.objects.get(user=self.user).lookahead_days, 7)
        self.assertFalse(Destination.objects.filter(user=self.user).exists())
        self.assertContains(response, "알림 대상을 추가해 주세요")
        self.assertContains(response, "아직 등록된 알림 대상이 없어요")

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_schedule_save_ignores_webhook_fields(self, _dns):
        """Webhooks are added on the 알림 대상 tab; the schedule form never creates one."""
        response = self.post(webhook_url=DISCORD_URL)

        self.assertRedirects(response, reverse("notification_settings"))
        self.assertEqual(NotificationRule.objects.get(user=self.user).lookahead_days, 7)
        self.assertFalse(Destination.objects.filter(user=self.user).exists())

    @patch("learningx_alert.network.socket.getaddrinfo", return_value=PUBLIC_DNS)
    def test_invalid_rule_saves_nothing_and_never_echoes_webhook(self, _dns):
        response = self.post(lookahead_days="30", webhook_url=DISCORD_URL)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(NotificationRule.objects.filter(user=self.user).exists())
        self.assertFalse(Destination.objects.filter(user=self.user).exists())
        self.assertNotContains(response, DISCORD_URL, status_code=400)

    def test_invalid_alarm_keeps_existing_rule_unchanged(self):
        make_rule(self.user, time(8, 0), lookahead_days=3)

        response = self.post(**{"alarms-0-days": []})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(NotificationRule.objects.get(user=self.user).lookahead_days, 3)
        self.assertContains(response, "data-dirty", status_code=400)

    def test_existing_destination_is_kept_when_url_left_blank(self):
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(DISCORD_URL),
        )

        response = self.post(lookahead_days="5")

        self.assertRedirects(response, reverse("notification_settings"))
        self.assertEqual(NotificationRule.objects.get(user=self.user).lookahead_days, 5)
        self.assertEqual(
            decrypt_secret(Destination.objects.get(user=self.user).encrypted_webhook_url),
            DISCORD_URL,
        )

    def test_changing_provider_without_url_only_saves_rule(self):
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(DISCORD_URL),
        )

        response = self.post(kind=Destination.Kind.SLACK)

        self.assertRedirects(response, reverse("notification_settings"))
        self.assertTrue(NotificationRule.objects.filter(user=self.user).exists())
        self.assertEqual(Destination.objects.get(user=self.user).kind, Destination.Kind.DISCORD)


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class UxPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.client.force_login(self.user)

    def test_stale_scheduler_notice_is_gone_and_labels_have_no_colon(self):
        response = self.client.get(reverse("notification_settings"))

        self.assertNotContains(response, "자동 알림 실행은 아직 시작되지 않았습니다")
        self.assertContains(response, ">마감 조회 범위</label>")
        self.assertNotContains(response, "범위:</label>")
        # One for the main nav item, one for the 알림 시각 sub-tab.
        self.assertContains(response, 'aria-current="page"', count=2)

    def test_dashboard_warns_when_destination_is_missing(self):
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="김학재",
            encrypted_token=encrypt_secret("canvas-secret"),
            verified_at=timezone.now(),
        )
        CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=1,
            course_name="디지털시스템_ICE3024_42(임완수)",
            enabled=True,
            include_assignments=True,
        )

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'aria-label="주 메뉴"')
        self.assertContains(response, "등록된 알림 대상이 없어서 예약 알림이 가지 않아요")
        self.assertNotContains(response, "내 로컬 계정과 이력 삭제")
        self.assertContains(response, 'action="/connection/preview/" data-loading')
        self.assertContains(response, 'id="loading-veil"')
        self.assertContains(response, "app.js")

    @patch("accounts.views.collect_for_user")
    def test_preview_groups_items_and_shows_message_text(self, collect):
        due = timezone.now() + timezone.timedelta(days=2)
        collect.return_value = CollectionResult(
            (AlertItem(1, "디지털시스템_ICE3024_42(임완수)", "x", "lecture", "week 5", due, ""),),
            (CourseOutcome(1, "디지털시스템_ICE3024_42(임완수)", "ok"),),
        )
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="김학재",
            encrypted_token=encrypt_secret("canvas-secret"),
            verified_at=timezone.now(),
        )

        response = self.client.post(reverse("preview"))

        self.assertContains(response, "D-2")
        self.assertContains(response, "보낼 메시지")
        self.assertContains(response, "- [강의] week 5")
        self.assertContains(response, "\n디지털시스템\n", html=False)
        self.assertContains(response, "<span>디지털시스템 ·", html=False)
