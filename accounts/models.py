from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


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


WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")
EVERY_DAY = 0b1111111
WEEKDAYS_ONLY = 0b0011111
WEEKEND_ONLY = 0b1100000


def weekdays_summary(mask):
    """Korean summary of a weekday bitmask (bit 0 = Monday)."""
    if mask == EVERY_DAY:
        return "매일"
    if mask == WEEKDAYS_ONLY:
        return "평일"
    if mask == WEEKEND_ONLY:
        return "주말"
    return " ".join(label for index, label in enumerate(WEEKDAY_LABELS) if mask & (1 << index))


class AlarmTime(models.Model):
    """One alarm-clock style slot: a KST time on chosen weekdays."""

    MAX_PER_RULE = 5

    rule = models.ForeignKey(
        NotificationRule,
        on_delete=models.CASCADE,
        related_name="alarms",
    )
    time = models.TimeField(default=time(9, 0))
    # Bit 0 = Monday ... bit 6 = Sunday, matching date.weekday().
    weekdays = models.PositiveSmallIntegerField(
        default=EVERY_DAY,
        validators=(MinValueValidator(1), MaxValueValidator(EVERY_DAY)),
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("rule", "time"),
                name="unique_rule_alarm_time",
            ),
            models.CheckConstraint(
                condition=Q(weekdays__gte=1) & Q(weekdays__lte=EVERY_DAY),
                name="alarm_weekdays_in_range",
            ),
        ]
        ordering = ("time", "id")

    def runs_on(self, weekday):
        return bool(self.weekdays & (1 << weekday))

    @property
    def weekdays_display(self):
        return weekdays_summary(self.weekdays)


DEFAULT_ALARM_TIME = time(9, 0)


def ensure_default_rule(user):
    """Give a user the default schedule (3 days, daily 09:00) if they have none.

    A rule with at least one alarm row is left untouched, including one whose
    alarms are all switched off: that is the user's choice. Returns the rule.
    """
    rule, _ = NotificationRule.objects.get_or_create(user=user)
    if not rule.alarms.exists():
        AlarmTime.objects.get_or_create(
            rule=rule,
            time=DEFAULT_ALARM_TIME,
            defaults={"weekdays": EVERY_DAY, "enabled": True},
        )
    return rule


class Destination(models.Model):
    """One place a user's alerts go. A user may have several.

    `encrypted_webhook_url` holds the encrypted secret for every kind: the
    webhook URL for Discord/Slack, the PushSubscription JSON for web push.
    """

    MAX_PER_USER = 10

    class Kind(models.TextChoices):
        DISCORD = "discord", "Discord"
        SLACK = "slack", "Slack"
        WEBPUSH = "webpush", "브라우저 푸시"

    class Status(models.TextChoices):
        UNTESTED = "untested", "시험 전"
        SUCCEEDED = "succeeded", "시험 성공"
        DEFINITELY_FAILED = "definitely_failed", "전송 실패"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="destinations",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    label = models.CharField(max_length=64, blank=True)
    encrypted_webhook_url = models.TextField()
    # Keyed hash of the secret target, so the same webhook or browser is not
    # registered twice without storing anything reversible.
    target_fingerprint = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.UNTESTED,
    )
    last_tested_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "target_fingerprint"),
                condition=~Q(target_fingerprint=""),
                name="unique_user_destination_target",
            )
        ]
        ordering = ("created_at", "id")

    @property
    def display_name(self):
        return self.label or self.get_kind_display()


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
    destination = models.ForeignKey(
        Destination,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="deliveries",
    )
    destination_kind = models.CharField(max_length=16, choices=Destination.Kind.choices)
    destination_label = models.CharField(max_length=64, blank=True)
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
                fields=("run", "destination", "part_number"),
                name="unique_run_destination_part",
            )
        ]
        ordering = ("id",)


class ExcludedItem(models.Model):
    """An assignment or lecture the user muted.

    The mute is tied to the deadline it was set against: if the course moves
    the deadline, the item alerts again (the exclusion is dropped).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="excluded_items",
    )
    canvas_course_id = models.BigIntegerField()
    course_name = models.CharField(max_length=255)
    item_type = models.CharField(max_length=32)
    external_id = models.CharField(max_length=128)
    title = models.CharField(max_length=500)
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "canvas_course_id", "item_type", "external_id"),
                name="unique_user_excluded_item",
            )
        ]
        ordering = ("due_at", "id")

    def key(self):
        return (self.canvas_course_id, self.item_type, self.external_id)


class Feedback(models.Model):
    """A bug report or suggestion sent from the floating feedback button."""

    class Category(models.TextChoices):
        BUG = "bug", "오류 제보"
        IDEA = "idea", "의견"
        OTHER = "other", "기타"

    class Status(models.TextChoices):
        NEW = "new", "새 피드백"
        DONE = "done", "처리함"

    MAX_MESSAGE = 2000

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    category = models.CharField(max_length=16, choices=Category.choices)
    message = models.TextField(max_length=MAX_MESSAGE)
    # Only when the user leaves "이 화면 정보 같이 보내기" on. Never tokens or URLs
    # with queries: page is a path, client is a coarse browser/OS label.
    page_path = models.CharField(max_length=200, blank=True)
    client = models.CharField(max_length=80, blank=True)
    standalone = models.BooleanField(null=True, blank=True)
    app_revision = models.CharField(max_length=40, blank=True)
    latest_run_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "피드백"
        verbose_name_plural = "피드백"

    def __str__(self):
        return f"#{self.pk} {self.get_category_display()}"
