from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.models import CanvasConnection, CourseSelection
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


@override_settings(
    CREDENTIAL_ENCRYPTION_KEYS=[KEY],
    CANVAS_BASE_URL="https://canvas.skku.edu",
)
class PreviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.other = get_user_model().objects.create_user(username="other@example.com")
        self.token = "preview-token-must-not-appear"
        self.connection = CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="김학재",
            encrypted_token=encrypt_secret(self.token),
            verified_at=timezone.now(),
        )
        CourseSelection.objects.create(
            user=self.other,
            canvas_course_id=999,
            course_name="타인의 비공개 과목",
            enabled=True,
            include_assignments=True,
        )

    def result(self):
        return CollectionResult(
            items=(
                AlertItem(
                    canvas_course_id=101,
                    course_name="전자회로",
                    external_id="11",
                    item_type="assignment",
                    title="증폭기 과제",
                    due_at=datetime(2026, 9, 26, 15, 30, tzinfo=UTC),
                    observed_state="unsubmitted",
                ),
            ),
            outcomes=(
                CourseOutcome(
                    canvas_course_id=101,
                    course_name="전자회로",
                    status="success",
                    no_deadline_count=2,
                ),
                CourseOutcome(
                    canvas_course_id=102,
                    course_name="디지털시스템",
                    status="failed",
                    error_code="submission_state_failed",
                    safe_summary="일부 과제의 제출 상태를 확인하지 못했습니다.",
                ),
            ),
        )

    def test_preview_requires_login(self):
        response = self.client.post(reverse("preview"))

        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("preview")}',
        )

    def test_preview_rejects_get(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("preview")).status_code, 405)

    def test_preview_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        self.assertEqual(client.post(reverse("preview")).status_code, 403)

    @patch("accounts.views.collect_for_user")
    def test_preview_shows_kst_deadline_no_deadline_count_and_safe_failure(self, collect):
        collect.return_value = self.result()
        self.client.force_login(self.user)

        response = self.client.post(reverse("preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "증폭기 과제")
        self.assertContains(response, "9월 27일")
        self.assertContains(response, "증폭기 과제 · 00:30")
        self.assertContains(response, "마감 없음 2건")
        self.assertContains(response, "확인 실패")
        self.assertContains(response, "일부 과제의 제출 상태를 확인하지 못했습니다.")
        self.assertContains(response, 'data-error-code="submission_state_failed"')
        self.assertNotContains(response, "<code>submission_state_failed</code>")
        self.assertNotContains(response, "조금 뒤에 다시 조회해 보세요.")

    @patch("accounts.views.collect_for_user")
    def test_canvas_outage_explains_it_is_temporary(self, collect):
        result = self.result()
        outage = replace(
            result.outcomes[1],
            error_code="lectures_failed",
            safe_summary="Canvas 응답 오류로 강의 목록을 확인하지 못했습니다.",
        )
        collect.return_value = replace(result, outcomes=(result.outcomes[0], outage))
        self.client.force_login(self.user)

        response = self.client.post(reverse("preview"))

        self.assertContains(response, "Canvas 응답 오류로 강의 목록을 확인하지 못했습니다.")
        self.assertContains(response, "조금 뒤에 다시 조회해 보세요.")
        self.assertNotContains(response, "<code>lectures_failed</code>")

    @patch("accounts.views.collect_for_user")
    def test_preview_uses_current_user_and_never_renders_credentials(self, collect):
        collect.return_value = self.result()
        self.client.force_login(self.user)

        response = self.client.post(reverse("preview"))

        collect.assert_called_once()
        self.assertEqual(collect.call_args.args[0], self.user)
        self.assertNotContains(response, "타인의 비공개 과목")
        self.assertNotContains(response, self.token)
        self.assertNotContains(response, self.connection.encrypted_token)

    @patch("accounts.views.collect_for_user")
    def test_missing_canvas_connection_redirects_safely(self, collect):
        collect.side_effect = CanvasConnection.DoesNotExist
        self.client.force_login(self.user)

        response = self.client.post(reverse("preview"), follow=True)

        self.assertRedirects(response, reverse("dashboard"))
        self.assertContains(response, "Canvas를 먼저 연결해 주세요.")
