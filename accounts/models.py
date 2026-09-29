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
    # Set when Canvas rejects the stored token (HTTP 401); cleared on reconnect.
    needs_reconnect = models.BooleanField(default=False)

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
    term_name = models.CharField(max_length=128, blank=True)
    term_start_at = models.DateTimeField(blank=True, null=True)
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


class ScheduledRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        RUNNING = "running", "실행 중"
        SUCCEEDED = "succeeded", "성공"
        EMPTY = "empty", "보낼 항목 없음"
        FAILED = "failed", "실패"
        INTERRUPTED = "interrupted", "중단됨"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scheduled_runs",
    )
    scheduled_for = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    safe_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "scheduled_for"),
                name="unique_user_scheduled_slot",
            )
        ]
        ordering = ("-scheduled_for",)


class CourseRunResult(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "성공"
        EMPTY = "empty", "항목 없음"
        FAILED = "failed", "실패"

    run = models.ForeignKey(
        ScheduledRun,
        on_delete=models.CASCADE,
        related_name="course_results",
    )
    canvas_course_id = models.BigIntegerField()
    course_name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices)
    error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("run", "canvas_course_id"),
                name="unique_run_course_result",
            )
        ]


class RunItem(models.Model):
    run = models.ForeignKey(
        ScheduledRun,
        on_delete=models.CASCADE,
        related_name="items",
    )
    canvas_course_id = models.BigIntegerField()
    external_id = models.CharField(max_length=128)
    item_type = models.CharField(max_length=32)
    title = models.CharField(max_length=500)
    due_at = models.DateTimeField()
    observed_state = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "run",
                    "canvas_course_id",
                    "external_id",
                    "item_type",
                    "due_at",
                ),
                name="unique_run_item_identity",
            )
        ]
        ordering = ("due_at", "id")


class Delivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        SENDING = "sending", "전송 중"
        SUCCEEDED = "succeeded", "성공"
        DEFINITELY_FAILED = "definitely_failed", "전송 실패"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    run = models.ForeignKey(
        ScheduledRun,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    destination_kind = models.CharField(max_length=16, choices=Destination.Kind.choices)
    part_number = models.PositiveSmallIntegerField()
    idempotency_key = models.CharField(max_length=64, unique=True)
    provider_confirmation_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    safe_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("run", "part_number"),
                name="unique_run_delivery_part",
            )
        ]
        ordering = ("part_number",)
