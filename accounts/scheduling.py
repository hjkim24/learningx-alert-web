from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction

from .models import NotificationRule, ScheduledRun


SEOUL = ZoneInfo("Asia/Seoul")


def matching_slot(rule, now):
    local_now = now.astimezone(SEOUL)
    for configured in (rule.first_time, rule.second_time):
        if configured is None:
            continue
        slot_time = configured.replace(second=0, microsecond=0)
        if (slot_time.hour, slot_time.minute) == (local_now.hour, local_now.minute):
            local_slot = datetime.combine(local_now.date(), slot_time, tzinfo=SEOUL)
            return local_slot.astimezone(UTC)
    return None


def claim_due_runs(now):
    rules = (
        NotificationRule.objects.filter(
            user__destination__isnull=False,
            user__canvas_connection__isnull=False,
            user__course_selections__enabled=True,
            user__course_selections__include_assignments=True,
        )
        .select_related("user")
        .distinct()
    )
    claimed = []
    for rule in rules:
        slot = matching_slot(rule, now)
        if slot is None:
            continue
        try:
            with transaction.atomic():
                run, created = ScheduledRun.objects.get_or_create(
                    user=rule.user,
                    scheduled_for=slot,
                )
        except IntegrityError:
            continue
        if created:
            claimed.append(run)
    return tuple(claimed)
