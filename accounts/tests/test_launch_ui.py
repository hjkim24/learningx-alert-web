"""Pre-launch UI checks: auth/error pages, share tags, dashboard order, and no internal codes."""

from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.models import (
    CanvasConnection,
    CourseRunResult,
    CourseSelection,
    Delivery,
    Destination,
    RunItem,
    ScheduledRun,
)
from accounts.notifications import render_notification


def make_user(name="launch"):
    return get_user_model().objects.create_user(username=f"{name}@example.com", email=f"{name}@example.com")


def connect(user, *, needs_reconnect=False):
    return CanvasConnection.objects.create(
        user=user, canvas_user_id="1", canvas_name="학생", encrypted_token="x",
        verified_at=timezone.now(), needs_reconnect=needs_reconnect,
    )


class AuthAndErrorPagesTests(TestCase):
    def test_cancelled_google_login_uses_the_site_layout(self):
        page = Client().get(reverse("socialaccount_login_cancelled"))

        self.assertContains(page, "로그인을 취소했어요")
        self.assertContains(page, 'class="site-header"')
        self.assertContains(page, reverse("account_login"))
        self.assertNotContains(page, "Menu:")

    def test_failed_google_login_explains_in_app_browsers(self):
        page = Client().get(reverse("socialaccount_login_error"))

        self.assertContains(page, "Google 로그인에 실패했어요", status_code=401)
        self.assertContains(page, "Safari나 Chrome", status_code=401)

    def test_google_login_by_get_asks_to_continue_with_a_post_button(self):
        page = Client().get("/accounts/google/login/")

        self.assertContains(page, "Google로 계속하기")
        self.assertContains(page, 'method="post"')
        self.assertContains(page, 'class="site-header"')

    def test_logout_by_get_confirms_with_a_post_button(self):
        client = Client()
        client.force_login(make_user())

        page = client.get(reverse("account_logout"))

        self.assertContains(page, "로그아웃할까요?")
        self.assertContains(page, f'action="{reverse("account_logout")}"')

    def test_unknown_page_is_a_styled_korean_404(self):
        page = Client().get("/no-such-page/")

        self.assertContains(page, "페이지를 찾을 수 없어요", status_code=404)
        self.assertContains(page, 'class="site-header"', status_code=404)

    def test_server_error_page_renders_without_request_context(self):
        html = render_to_string("500.html")

        self.assertIn("잠시 문제가 생겼어요", html)
        self.assertNotIn("파일럿", html)

    def test_csrf_failure_page_is_korean(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(make_user())

        page = client.post(reverse("canvas_connect"), {"token": "t"})

        self.assertContains(page, "보안 확인", status_code=403)


class ShareTagsTests(TestCase):
    def test_pages_carry_description_and_open_graph_image(self):
        page = Client().get(reverse("account_login"))

        self.assertContains(page, '<meta name="description"')
        self.assertContains(page, 'property="og:title"')
        self.assertContains(page, 'property="og:image" content="http://testserver/static/og-image.png"')
        self.assertContains(page, 'name="twitter:card" content="summary_large_image"')


class DashboardOrderTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_new_user_sees_connection_right_after_the_guide_without_empty_cards(self):
        page = self.client.get(reverse("dashboard")).content.decode()

        self.assertLess(page.index('id="start-guide"'), page.index('id="canvas-title"'))
        self.assertNotIn(f'action="{reverse("preview")}"', page)
        self.assertNotIn('id="next-run-title"', page)

    def test_reconnect_brings_the_connection_up(self):
        connect(self.user, needs_reconnect=True)

        page = self.client.get(reverse("dashboard")).content.decode()

        self.assertLess(page.index('id="canvas-title"'), page.index('id="remaining-title"'))

    def test_healthy_connection_keeps_it_at_the_bottom(self):
        connect(self.user)

        page = self.client.get(reverse("dashboard")).content.decode()

        self.assertLess(page.index('id="remaining-title"'), page.index('id="canvas-title"'))
        self.assertIn(f'action="{reverse("preview")}"', page)


class InternalCodeTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        connect(self.user)
        now = timezone.now()
        self.run = ScheduledRun.objects.create(
            user=self.user, scheduled_for=now - timedelta(hours=1), status=ScheduledRun.Status.NEEDS_REVIEW,
            safe_error_code="delivery_ambiguous", started_at=now, finished_at=now,
        )
        CourseRunResult.objects.create(
            run=self.run, canvas_course_id=101, course_name="디지털시스템_ICE3024_42(임완수)", status="success",
        )
        RunItem.objects.create(
            run=self.run, canvas_course_id=101, external_id="1", item_type="quiz", title="퀴즈 3",
            due_at=now + timedelta(days=1), observed_state="unsubmitted",
        )
        Delivery.objects.create(
            run=self.run, destination_kind="discord", destination_label="스터디", part_number=1,
            idempotency_key="k1", status="needs_review", safe_error_code="delivery_ambiguous", finished_at=now,
        )

    def test_run_detail_shows_course_title_kind_and_plain_reason(self):
        page = self.client.get(reverse("run_detail", args=[self.run.pk]))

        self.assertContains(page, "디지털시스템 · 퀴즈 3")
        self.assertNotContains(page, "과목 101")
        self.assertNotContains(page, "unsubmitted")
        self.assertNotContains(page, "<code>")
        self.assertContains(page, 'data-error-code="delivery_ambiguous"')
        self.assertContains(page, "전송됐는지 확인하지 못했어요")

    def test_dashboard_problem_rows_show_a_reason_not_a_code(self):
        page = self.client.get(reverse("dashboard"))

        self.assertContains(page, "전송됐는지 확인하지 못했어요")
        self.assertNotContains(page, "<code>")

    def test_chat_message_hides_the_error_code(self):
        result = CollectionResult(
            items=(AlertItem(1, "과목", "1", "assignment", "과제", datetime(2026, 9, 27, tzinfo=UTC), "unsubmitted"),),
            outcomes=(CourseOutcome(2, "재료", "failed", "assignments_failed", "과제 목록을 확인하지 못했어요."),),
        )

        text = render_notification(result, datetime(2026, 9, 26, tzinfo=UTC))

        self.assertIn("과제 목록을 확인하지 못했어요.", text)
        self.assertNotIn("assignments_failed", text)


class SettingsPagesTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        connect(self.user)

    def test_course_page_without_courses_has_no_save_bar(self):
        page = self.client.get(reverse("course_settings"))

        self.assertNotContains(page, 'class="sticky-actions')

    def test_course_page_with_courses_keeps_the_save_bar(self):
        CourseSelection.objects.create(user=self.user, canvas_course_id=1, course_name="과목")

        page = self.client.get(reverse("course_settings"))

        self.assertContains(page, 'class="sticky-actions')

    def test_full_destination_list_replaces_the_webhook_form_with_a_note(self):
        for index in range(Destination.MAX_PER_USER):
            Destination.objects.create(user=self.user, kind="discord", encrypted_webhook_url=f"x{index}")

        page = self.client.get(reverse("destination_settings"))

        self.assertNotContains(page, "webhook-panel")
        self.assertContains(page, "먼저 하나를 삭제해 주세요")

    def test_empty_excluded_list_keeps_its_sentence_in_one_line(self):
        page = self.client.get(reverse("excluded_items"))

        self.assertContains(
            page,
            f'<span>알림 끈 항목이 없어요. <a href="{reverse("dashboard")}">대시보드</a>',
        )
