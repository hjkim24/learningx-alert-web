from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class CanvasConnection(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="canvas_connection",
    )
    canvas_user_id = models.CharField(max_length=128)
    canvas_name = models.CharField(max_length=255)
    encrypted_token = models.TextField()
    verified_at = models.DateTimeField()

    def __str__(self):
        return f"Canvas connection for user {self.user_id}"


class CourseSelection(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_selections",
    )
    canvas_course_id = models.BigIntegerField()
    course_name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=False)
    include_assignments = models.BooleanField(default=False)
    include_lectures = models.BooleanField(default=False)
    include_required_materials = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "canvas_course_id"),
                name="unique_user_canvas_course",
            )
        ]
        ordering = ("course_name", "canvas_course_id")


class NotificationRule(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_rule",
    )
    lookahead_days = models.PositiveSmallIntegerField(
        default=3,
        validators=(MinValueValidator(1), MaxValueValidator(14)),
    )
    first_time = models.TimeField(default=time(9, 0))
    second_time = models.TimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(second_time__isnull=True)
                | ~Q(first_time=F("second_time")),
                name="notification_times_are_distinct",
            )
        ]


class Destination(models.Model):
    class Kind(models.TextChoices):
        DISCORD = "discord", "Discord"
        SLACK = "slack", "Slack"

    class Status(models.TextChoices):
        UNTESTED = "untested", "시험 전"
        SUCCEEDED = "succeeded", "시험 성공"
        DEFINITELY_FAILED = "definitely_failed", "전송 실패"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="destination",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    encrypted_webhook_url = models.TextField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.UNTESTED,
    )
    last_tested_at = models.DateTimeField(blank=True, null=True)
