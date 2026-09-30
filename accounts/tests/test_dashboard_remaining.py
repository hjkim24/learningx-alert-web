from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    CanvasConnection,
    CourseRunResult,
    ExcludedItem,
    RunItem,
    ScheduledRun,
)


class DashboardRemainingItemsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="remain@example.com")
        self.client.force_login(self.user)
        self.now = timezone.now()
        CanvasConnection.objects.create(
            user=self.user,
            canvas_user_id="1",
            canvas_name="학생",
            encrypted_token="x",
            verified_at=self.now,
        )

    def make_run(self, hours_ago, *, finished=True, courses=(("101", "전자회로 (101)", "success"),)):
        run = ScheduledRun.objects.create(
            user=self.user,
            scheduled_for=self.now - timedelta(hours=hours_ago),
            status=ScheduledRun.Status.SUCCEEDED if finished else ScheduledRun.Status.RUNNING,
            finished_at=self.now if finished else None,
        )
        for course_id, name, status in courses:
            CourseRunResult.objects.create(
                run=run, canvas_course_id=int(course_id), course_name=name, status=status
            )
        return run

    def add_item(self, run, title, due_in_hours, external_id=None, course_id=101):
        return RunItem.objects.create(
            run=run,
            canvas_course_id=course_id,
            external_id=external_id or title,
            item_type="assignment",
            title=title,
            due_at=self.now + timedelta(hours=due_in_hours),
            observed_state="unsubmitted",
        )

    def dashboard(self):
        return self.client.get(reverse("dashboard")).content.decode()

    def test_lists_latest_finished_run_items_still_due_and_not_muted(self):
        old = self.make_run(48)
        self.add_item(old, "옛 실행 과제", 30)
        latest = self.make_run(2)
        self.add_item(latest, "남은 과제", 30)
        self.add_item(latest, "지난 과제", -1)
        muted = self.add_item(latest, "끈 과제", 40)
        ExcludedItem.objects.create(
            user=self.user, canvas_course_id=101, course_name="전자회로", item_type="assignment",
            external_id=muted.external_id, title=muted.title, due_at=muted.due_at,
        )
        unfinished = self.make_run(0, finished=False)
        self.add_item(unfinished, "진행 중 실행 과제", 30)

        page = self.dashboard()

        self.assertIn("남은 과제·강의", page)
        self.assertIn("남은 과제", page)
        self.assertIn('data-item-count>1<', page)
        for hidden in ("옛 실행 과제", "지난 과제", "끈 과제", "진행 중 실행 과제"):
            self.assertNotIn(hidden, page)
        self.assertIn("알림 기준", page)
        self.assertIn("data-exclude", page)  # same in-place mute form as the preview

    def test_moved_deadline_is_not_hidden_by_an_old_mute(self):
        run = self.make_run(1)
        item = self.add_item(run, "마감 바뀐 과제", 50)
        ExcludedItem.objects.create(
            user=self.user, canvas_course_id=101, course_name="전자회로", item_type="assignment",
            external_id=item.external_id, title=item.title, due_at=item.due_at - timedelta(days=1),
        )

        self.assertIn("마감 바뀐 과제", self.dashboard())

    def test_failed_course_is_called_out(self):
        self.make_run(1, courses=(("101", "전자회로 (101)", "success"), ("202", "회로이론 (202)", "failed")))

        page = self.dashboard()

        self.assertIn("불러오지 못한 과목", page)
        self.assertIn("회로이론", page)
        self.assertIn("마감이 남은 과제·강의가 없어요", page)

    def test_before_first_run_shows_first_run_hint(self):
        self.assertIn("첫 예약 알림이 가고 나면", self.dashboard())

    def test_hidden_without_canvas_connection(self):
        CanvasConnection.objects.filter(user=self.user).delete()

        self.assertNotIn("남은 과제·강의", self.dashboard())


class PwaGuideLinkTests(TestCase):
    def test_guide_is_linked_from_dashboard_destinations_and_token_guide(self):
        user = get_user_model().objects.create_user(username="links@example.com")
        self.client.force_login(user)
        guide = reverse("pwa_install_guide")
        CanvasConnection.objects.create(
            user=user, canvas_user_id="1", canvas_name="학생", encrypted_token="x",
            verified_at=timezone.now(),
        )
        from accounts.models import CourseSelection

        CourseSelection.objects.create(
            user=user, canvas_course_id=1, course_name="전자회로", enabled=True, include_assignments=True
        )

        self.assertContains(self.client.get(reverse("dashboard")), guide)  # no destination yet
        self.assertContains(self.client.get(reverse("destination_settings")), guide)
        self.assertContains(self.client.get(reverse("canvas_token_guide")), guide)
