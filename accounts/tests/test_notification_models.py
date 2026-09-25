from datetime import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import CourseSelection, Destination, NotificationRule


class NotificationModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pilot@example.com")

    def test_new_course_types_are_all_opt_in(self):
        course = CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="회로이론",
        )

        self.assertFalse(course.enabled)
        self.assertFalse(course.include_assignments)
        self.assertFalse(course.include_lectures)
        self.assertFalse(course.include_required_materials)

    def test_course_identity_is_unique_per_user(self):
        CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="A",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseSelection.objects.create(
                user=self.user,
                canvas_course_id=101,
                course_name="B",
            )

    def test_rule_rejects_equal_daily_times(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            NotificationRule.objects.create(
                user=self.user,
                lookahead_days=3,
                first_time=time(9, 0),
                second_time=time(9, 0),
            )

    def test_deleting_user_cascades_notification_configuration(self):
        CourseSelection.objects.create(
            user=self.user,
            canvas_course_id=101,
            course_name="A",
        )
        NotificationRule.objects.create(user=self.user, first_time=time(9, 0))
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url="ciphertext",
        )

        self.user.delete()

        self.assertFalse(CourseSelection.objects.exists())
        self.assertFalse(NotificationRule.objects.exists())
        self.assertFalse(Destination.objects.exists())
