import hashlib
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from .collection import collect_for_user
from .models import (
    CourseRunResult,
    Delivery,
    Destination,
    NotificationRule,
    RunItem,
    ScheduledRun,
)
from .notifications import (
    AmbiguousDeliveryError,
    DefiniteDeliveryError,
    render_notification,
    send_webhook_part,
    split_message,
)
from .services import decrypt_secret


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


def delivery_key(run, part_number, part):
    part_hash = hashlib.sha256(part.encode()).hexdigest()
    identity = (
        f"{run.user_id}:{run.scheduled_for.isoformat()}:{part_number}:{part_hash}"
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _finish_run(run, status, now, safe_error_code=""):
    ScheduledRun.objects.filter(pk=run.pk).update(
        status=status,
        safe_error_code=safe_error_code,
        finished_at=now,
    )
    run.status = status
    run.safe_error_code = safe_error_code
    run.finished_at = now
    return run


def _finish_open_deliveries(run, status, safe_error_code, now):
    Delivery.objects.filter(
        run=run,
        status__in=(Delivery.Status.PENDING, Delivery.Status.SENDING),
    ).update(
        status=status,
        safe_error_code=safe_error_code,
        finished_at=now,
    )


@sensitive_variables()
def execute_run(
    run,
    now,
    collector=collect_for_user,
    sender=send_webhook_part,
):
    run.refresh_from_db(fields=("status",))
    terminal_statuses = {
        ScheduledRun.Status.SUCCEEDED,
        ScheduledRun.Status.EMPTY,
        ScheduledRun.Status.FAILED,
        ScheduledRun.Status.NEEDS_REVIEW,
    }
    if run.status in terminal_statuses:
        return run

    ScheduledRun.objects.filter(pk=run.pk).update(
        status=ScheduledRun.Status.RUNNING,
        safe_error_code="",
        started_at=now,
        finished_at=None,
    )
    run.status = ScheduledRun.Status.RUNNING
    run.safe_error_code = ""
    run.started_at = now
    run.finished_at = None

    result = collector(run.user, now)
    with transaction.atomic():
        run.course_results.all().delete()
        run.items.all().delete()
        CourseRunResult.objects.bulk_create(
            [
                CourseRunResult(
                    run=run,
                    canvas_course_id=outcome.canvas_course_id,
                    course_name=outcome.course_name,
                    status=outcome.status,
                    error_code=outcome.error_code,
                    safe_summary=outcome.safe_summary,
                )
                for outcome in result.outcomes
            ]
        )
        RunItem.objects.bulk_create(
            [
                RunItem(
                    run=run,
                    canvas_course_id=item.canvas_course_id,
                    external_id=item.external_id,
                    item_type=item.item_type,
                    title=item.title,
                    due_at=item.due_at,
                    observed_state=item.observed_state,
                )
                for item in result.items
            ]
        )

    has_failures = any(outcome.status == "failed" for outcome in result.outcomes)
    if not result.items and not has_failures:
        return _finish_run(run, ScheduledRun.Status.EMPTY, now)

    destination = Destination.objects.filter(user_id=run.user_id).first()
    if destination is None:
        return _finish_run(
            run,
            ScheduledRun.Status.FAILED,
            now,
            "destination_missing",
        )

    parts = split_message(render_notification(result, now))
    with transaction.atomic():
        Delivery.objects.bulk_create(
            [
                Delivery(
                    run=run,
                    destination_kind=destination.kind,
                    part_number=part_number,
                    idempotency_key=delivery_key(run, part_number, part),
                )
                for part_number, part in enumerate(parts, start=1)
            ]
        )
    deliveries = tuple(run.deliveries.all())

    webhook_url = decrypt_secret(destination.encrypted_webhook_url)
    for delivery, part in zip(deliveries, parts, strict=True):
        with transaction.atomic():
            Delivery.objects.filter(
                pk=delivery.pk,
                status=Delivery.Status.PENDING,
            ).update(
                status=Delivery.Status.SENDING,
                started_at=now,
            )
        try:
            receipt = sender(destination.kind, webhook_url, part)
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.Status.SUCCEEDED,
                provider_confirmation_id=receipt,
                safe_error_code="",
                finished_at=now,
            )
        except DefiniteDeliveryError:
            _finish_open_deliveries(
                run,
                Delivery.Status.DEFINITELY_FAILED,
                "delivery_definite",
                now,
            )
            return _finish_run(
                run,
                ScheduledRun.Status.FAILED,
                now,
                "delivery_definite",
            )
        except AmbiguousDeliveryError:
            _finish_open_deliveries(
                run,
                Delivery.Status.NEEDS_REVIEW,
                "delivery_ambiguous",
                now,
            )
            return _finish_run(
                run,
                ScheduledRun.Status.NEEDS_REVIEW,
                now,
                "delivery_ambiguous",
            )
        except Exception:
            _finish_open_deliveries(
                run,
                Delivery.Status.NEEDS_REVIEW,
                "delivery_unexpected",
                now,
            )
            return _finish_run(
                run,
                ScheduledRun.Status.NEEDS_REVIEW,
                now,
                "delivery_unexpected",
            )

    return _finish_run(run, ScheduledRun.Status.SUCCEEDED, now)


def run_due_rules(
    now,
    claimed_runs=None,
    collector=collect_for_user,
    sender=send_webhook_part,
):
    runs = claim_due_runs(now) if claimed_runs is None else claimed_runs
    for run in runs:
        try:
            execute_run(run, now, collector=collector, sender=sender)
        except Exception:
            _finish_run(
                run,
                ScheduledRun.Status.FAILED,
                now,
                "run_failed",
            )
    return runs
