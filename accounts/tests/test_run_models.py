from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import CourseRunResult, Delivery, RunItem, ScheduledRun


class RunModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        self.slot = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)

    def create_run(self):
        return ScheduledRun.objects.create(user=self.user, scheduled_for=self.slot)

    def test_user_slot_is_unique(self):
        self.create_run()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_run()

    def test_item_identity_is_unique_inside_run(self):
        run = self.create_run()
        values = {
            "run": run,
            "canvas_course_id": 101,
            "external_id": "55",
            "item_type": "assignment",
            "title": "HW",
            "due_at": datetime(2026, 9, 27, 0, 0, tzinfo=UTC),
            "observed_state": "unsubmitted",
        }
        RunItem.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RunItem.objects.create(**values)

    def test_part_number_and_idempotency_key_are_unique(self):
        run = self.create_run()
        Delivery.objects.create(
            run=run,
            destination_kind="discord",
            part_number=1,
            idempotency_key="key-1",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Delivery.objects.create(
                run=run,
                destination_kind="discord",
                part_number=1,
                idempotency_key="key-2",
            )

        other_run = ScheduledRun.objects.create(
            user=self.user,
            scheduled_for=datetime(2026, 9, 26, 1, 0, tzinfo=UTC),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Delivery.objects.create(
                run=other_run,
                destination_kind="discord",
                part_number=1,
                idempotency_key="key-1",
            )

    def test_user_delete_cascades_every_run_record(self):
        run = self.create_run()
        CourseRunResult.objects.create(
            run=run,
            canvas_course_id=101,
            course_name="A",
            status="empty",
        )
        RunItem.objects.create(
            run=run,
            canvas_course_id=101,
            external_id="55",
            item_type="assignment",
            title="HW",
            due_at=datetime(2026, 9, 27, 0, 0, tzinfo=UTC),
            observed_state="unsubmitted",
        )
        Delivery.objects.create(
            run=run,
            destination_kind="discord",
            part_number=1,
            idempotency_key="key-1",
        )
        self.user.delete()
        self.assertFalse(ScheduledRun.objects.exists())
        self.assertFalse(CourseRunResult.objects.exists())
        self.assertFalse(RunItem.objects.exists())
        self.assertFalse(Delivery.objects.exists())
