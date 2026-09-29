from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import AlertItem, apply_exclusions, collect_for_user
from accounts.models import (
    CanvasConnection,
    CourseSelection,
    Destination,
    ExcludedItem,
    NotificationRule,
    ScheduledRun,
)
from accounts.scheduling import execute_run
from accounts.services import encrypt_secret
from accounts.tests.test_collection import FakeCanvasClient


KEY = Fernet.generate_key().decode()
DUE = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)


def item(external_id="55", due_at=DUE, item_type="assignment", course=101):
    return AlertItem(course, "전자회로", external_id, item_type, f"HW {external_id}", due_at, "unsubmitted")


def exclude(user, external_id="55", due_at=DUE, item_type="assignment", course=101):
    return ExcludedItem.objects.create(
        user=user,
        canvas_course_id=course,
        course_name="전자회로",
        item_type=item_type,
        external_id=external_id,
        title=f"HW {external_id}",
        due_at=due_at,
    )


class ApplyExclusionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")

    def test_matching_item_is_dropped_and_counted(self):
        exclude(self.user, "55")

        kept, excluded = apply_exclusions(self.user, [item("55"), item("56")])

        self.assertEqual([entry.external_id for entry in kept], ["56"])
        self.assertEqual(excluded, 1)

    def test_moved_deadline_alerts_again_and_forgets_the_mute(self):
        exclude(self.user, "55", due_at=DUE)

        kept, excluded = apply_exclusions(self.user, [item("55", due_at=DUE + timedelta(days=2))])

        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, 0)
        self.assertFalse(ExcludedItem.objects.exists())

    def test_type_and_course_are_part_of_the_identity(self):
        exclude(self.user, "55", item_type="assignment", course=101)

        kept, _ = apply_exclusions(
            self.user,
            [item("55", item_type="lecture"), item("55", course=202)],
        )

        self.assertEqual(len(kept), 2)

    def test_other_users_mutes_do_not_apply(self):
        exclude(self.other, "55")

        kept, excluded = apply_exclusions(self.user, [item("55")])

        self.assertEqual((len(kept), excluded), (1, 0))


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], CANVAS_BASE_URL="https://canvas.skku.edu")
class CollectionExclusionTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="Pilot",
            encrypted_token=encrypt_secret("token"),
            verified_at=timezone.now(),
        )
        NotificationRule.objects.create(user=self.user, lookahead_days=3)
        CourseSelection.objects.create(
            user=self.user, canvas_course_id=101, course_name="전자회로", enabled=True, include_assignments=True
        )
        self.fake = FakeCanvasClient("unused", "unused")
        self.fake.assignments_by_course[101] = [
            {"id": 55, "name": "HW 55", "due_at": "2026-09-27T00:00:00Z", "is_quiz_assignment": False},
            {"id": 56, "name": "HW 56", "due_at": "2026-09-27T00:00:00Z", "is_quiz_assignment": False},
        ]

    def collect(self):
        return collect_for_user(self.user, self.now, client_class=lambda _b, _t: self.fake)

    def test_excluded_item_is_missing_from_collection(self):
        exclude(self.user, "55")

        result = self.collect()

        self.assertEqual([entry.external_id for entry in result.items], ["56"])
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.outcomes[0].status, "success")

    def test_course_with_everything_muted_is_empty_not_failed(self):
        exclude(self.user, "55")
        exclude(self.user, "56")

        result = self.collect()

        self.assertEqual(result.items, ())
        self.assertEqual(result.outcomes[0].status, "empty")

    def test_scheduled_run_skips_muted_items(self):
        Destination.objects.create(
            user=self.user,
            kind="discord",
            encrypted_webhook_url=encrypt_secret("https://discord.com/api/webhooks/1/x"),
        )
        exclude(self.user, "55")
        run = ScheduledRun.objects.create(user=self.user, scheduled_for=self.now)
        sent = []

        execute_run(
            run,
            self.now,
            collector=lambda user, now: collect_for_user(user, now, client_class=lambda _b, _t: self.fake),
            sender=lambda kind, secret, part: sent.append(part) or "ok",
        )

        self.assertEqual(list(run.items.values_list("external_id", flat=True)), ["56"])
        self.assertIn("HW 56", sent[0])
        self.assertNotIn("HW 55", sent[0])


class ExclusionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        CourseSelection.objects.create(user=self.user, canvas_course_id=101, course_name="전자회로")
        self.client.force_login(self.user)
        self.data = {
            "canvas_course_id": "101",
            "item_type": "assignment",
            "external_id": "55",
            "due_at": DUE.isoformat(),
            "title": "HW 55",
        }

    def test_exclude_via_fetch_returns_json_and_stores_the_mute(self):
        response = self.client.post(reverse("item_exclude"), self.data, HTTP_ACCEPT="application/json")

        self.assertEqual(response.json(), {"ok": True, "excluded_count": 1})
        stored = ExcludedItem.objects.get(user=self.user)
        self.assertEqual((stored.external_id, stored.due_at, stored.course_name), ("55", DUE, "전자회로"))

    def test_exclude_without_js_redirects_to_the_list(self):
        response = self.client.post(reverse("item_exclude"), self.data, follow=True)

        self.assertRedirects(response, reverse("excluded_items"))
        self.assertContains(response, "이 항목의 알림을 껐어요.")
        self.assertContains(response, "HW 55")

    def test_excluding_twice_does_not_duplicate(self):
        self.client.post(reverse("item_exclude"), self.data)
        self.client.post(reverse("item_exclude"), self.data)

        self.assertEqual(ExcludedItem.objects.filter(user=self.user).count(), 1)

    def test_course_the_user_does_not_have_is_rejected(self):
        response = self.client.post(
            reverse("item_exclude"), {**self.data, "canvas_course_id": "999"}, HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExcludedItem.objects.exists())

    def test_malformed_input_is_rejected(self):
        for field, value in (
            ("item_type", "quiz"),
            ("external_id", ""),
            ("external_id", "x" * 129),
            ("due_at", "not-a-date"),
            ("due_at", "2026-09-27T00:00:00"),  # naive
            ("canvas_course_id", "abc"),
        ):
            with self.subTest(field=field, value=value[:20]):
                response = self.client.post(
                    reverse("item_exclude"), {**self.data, field: value}, HTTP_ACCEPT="application/json"
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(ExcludedItem.objects.exists())

    def test_include_restores_only_own_item(self):
        own = exclude(self.user)
        other = exclude(self.other)

        self.client.post(reverse("item_include", args=[other.pk]))
        response = self.client.post(reverse("item_include", args=[own.pk]), follow=True)

        self.assertContains(response, "다시 켰어요")
        self.assertFalse(ExcludedItem.objects.filter(pk=own.pk).exists())
        self.assertTrue(ExcludedItem.objects.filter(pk=other.pk).exists())

    def test_list_splits_upcoming_and_past_and_hides_other_users(self):
        exclude(self.user, "1", due_at=timezone.now() + timedelta(days=1))
        exclude(self.user, "2", due_at=timezone.now() - timedelta(days=1))
        exclude(self.other, "3", due_at=timezone.now() + timedelta(days=1))

        page = self.client.get(reverse("excluded_items"))

        self.assertEqual([entry.external_id for entry in page.context["upcoming"]], ["1"])
        self.assertEqual([entry.external_id for entry in page.context["past"]], ["2"])
        self.assertNotContains(page, "HW 3")

    def test_endpoints_require_login_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse("item_exclude")).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("item_exclude"), self.data).status_code, 403)
        anonymous = Client().post(reverse("item_exclude"), self.data)
        self.assertEqual(anonymous.status_code, 302)
        self.assertFalse(ExcludedItem.objects.exists())

    def test_schedule_tab_links_to_the_list_with_upcoming_count(self):
        exclude(self.user, "1", due_at=timezone.now() + timedelta(days=1))

        page = self.client.get(reverse("notification_settings"))

        self.assertContains(page, f'href="{reverse("excluded_items")}"')
        self.assertContains(page, "마감 전 1건")

    def test_user_delete_removes_mutes(self):
        exclude(self.user)

        self.user.delete()

        self.assertFalse(ExcludedItem.objects.exists())


class PreviewExclusionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        CanvasConnection.objects.create(
            user=self.user, canvas_user_id="1", canvas_name="P", encrypted_token="x", verified_at=timezone.now()
        )
        self.client.force_login(self.user)

    def preview(self, excluded_count):
        from unittest.mock import patch

        from accounts.collection import CollectionResult, CourseOutcome

        result = CollectionResult(
            (item("55", due_at=timezone.now() + timedelta(days=1)),),
            (CourseOutcome(101, "전자회로", "success"),),
            excluded_count,
        )
        with patch("accounts.views.collect_for_user", return_value=result):
            return self.client.post(reverse("preview"))

    def test_each_item_has_a_mute_form_with_its_identity(self):
        page = self.preview(0)

        self.assertContains(page, f'action="{reverse("item_exclude")}"')
        self.assertContains(page, 'name="external_id" value="55"')
        self.assertContains(page, 'name="item_type" value="assignment"')
        self.assertContains(page, "알림 끄기")
        self.assertContains(page, "data-excluded-note hidden")

    def test_muted_count_is_shown_with_a_link(self):
        page = self.preview(2)

        self.assertContains(page, "<strong data-excluded-count>2</strong>")
        self.assertContains(page, f'href="{reverse("excluded_items")}"')
