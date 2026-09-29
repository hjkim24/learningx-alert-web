import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from .collection import alert_selection_filter, collect_for_user
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
    SubscriptionGoneError,
    message_parts,
    send_to_destination,
)
from .services import decrypt_secret


SEOUL = ZoneInfo("Asia/Seoul")


def active_alarms(rule):
    """Enabled alarms of a rule; uses the prefetch cache when present."""
    return [alarm for alarm in rule.alarms.all() if alarm.enabled]


def matching_slot(rule, now):
    local_now = now.astimezone(SEOUL)
    weekday = local_now.weekday()
    for alarm in active_alarms(rule):
        slot_time = alarm.time.replace(second=0, microsecond=0)
        if (slot_time.hour, slot_time.minute) != (local_now.hour, local_now.minute):
            continue
        if not alarm.runs_on(weekday):
            continue
        local_slot = datetime.combine(local_now.date(), slot_time, tzinfo=SEOUL)
        return local_slot.astimezone(UTC)
    return None


def next_alarm_at(rule, now, *, current_slot_claimed=False):
    """Earliest upcoming alarm (KST datetime) within the next week, or None."""
    local_now = now.astimezone(SEOUL)
    local_minute = local_now.replace(second=0, microsecond=0)
    candidates = []
    for alarm in active_alarms(rule):
        slot_time = alarm.time.replace(second=0, microsecond=0)
        for offset in range(8):
            day = local_now.date() + timedelta(days=offset)
            if not alarm.runs_on(day.weekday()):
                continue
            candidate = datetime.combine(day, slot_time, tzinfo=SEOUL)
            if candidate < local_now or (
                current_slot_claimed and candidate == local_minute
            ):
                continue
            candidates.append(candidate)
            break
    return min(candidates) if candidates else None


def claim_due_runs(now):
    rules = (
        NotificationRule.objects.filter(
            alert_selection_filter("user__course_selections__"),
            user__destinations__isnull=False,
            user__canvas_connection__isnull=False,
            user__canvas_connection__needs_reconnect=False,
        )
        .select_related("user")
        .prefetch_related("alarms")
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


def delivery_key(run, part_number, part, destination_id=None):
    part_hash = hashlib.sha256(part.encode()).hexdigest()
    identity = (
        f"{run.user_id}:{run.scheduled_for.isoformat()}:{part_number}:{part_hash}"
    )
    if destination_id is not None:
        identity = f"{identity}:{destination_id}"
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


def _finish_open_deliveries(run, status, safe_error_code, now, destination=None):
    deliveries = Delivery.objects.filter(
        run=run,
        status__in=(Delivery.Status.PENDING, Delivery.Status.SENDING),
    )
    if destination is not None:
        deliveries = deliveries.filter(destination=destination)
    deliveries.update(
        status=status,
        safe_error_code=safe_error_code,
        finished_at=now,
    )


def _start_delivery(delivery, now):
    return (
        Delivery.objects.filter(
            pk=delivery.pk,
            status=Delivery.Status.PENDING,
        ).update(
            status=Delivery.Status.SENDING,
            started_at=now,
        )
        == 1
    )


@sensitive_variables()
def execute_run(
    run,
    now,
    collector=collect_for_user,
    sender=send_to_destination,
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
                    course_name=outcome.course_name[:255],
                    status=outcome.status,
                    error_code=outcome.error_code,
                    safe_summary=outcome.safe_summary[:255],
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
                    title=item.title[:500],
                    due_at=item.due_at,
                    observed_state=item.observed_state[:64],
                )
                for item in result.items
            ]
        )

    has_failures = any(outcome.status == "failed" for outcome in result.outcomes)
    if not result.items and not has_failures:
        return _finish_run(run, ScheduledRun.Status.EMPTY, now)

    destinations = tuple(Destination.objects.filter(user_id=run.user_id))
    if not destinations:
        return _finish_run(
            run,
            ScheduledRun.Status.FAILED,
            now,
            "destination_missing",
        )

    plans = [
        (destination, message_parts(destination.kind, result, now))
        for destination in destinations
    ]
    with transaction.atomic():
        Delivery.objects.bulk_create(
            [
                Delivery(
                    run=run,
                    destination=destination,
                    destination_kind=destination.kind,
                    destination_label=destination.display_name[:64],
                    part_number=part_number,
                    idempotency_key=delivery_key(
                        run, part_number, part, destination.pk
                    ),
                )
                for destination, parts in plans
                for part_number, part in enumerate(parts, start=1)
            ]
        )

    # Each destination is independent: one failing does not stop the others.
    ambiguous_codes = []
    definite_codes = []
    for destination, parts in plans:
        deliveries = tuple(
            run.deliveries.filter(destination=destination).order_by("part_number")
        )
        secret = decrypt_secret(destination.encrypted_webhook_url)
        for delivery, part in zip(deliveries, parts, strict=True):
            if not _start_delivery(delivery, now):
                _finish_open_deliveries(
                    run,
                    Delivery.Status.NEEDS_REVIEW,
                    "delivery_state_conflict",
                    now,
                )
                return _finish_run(
                    run,
                    ScheduledRun.Status.NEEDS_REVIEW,
                    now,
                    "delivery_state_conflict",
                )
            try:
                receipt = sender(destination.kind, secret, part)
                Delivery.objects.filter(pk=delivery.pk).update(
                    status=Delivery.Status.SUCCEEDED,
                    provider_confirmation_id=receipt,
                    safe_error_code="",
                    finished_at=now,
                )
            except SubscriptionGoneError:
                _finish_open_deliveries(
                    run,
                    Delivery.Status.DEFINITELY_FAILED,
                    "push_subscription_gone",
                    now,
                    destination,
                )
                # The browser unsubscribed; drop it so it is not retried forever.
                destination.delete()
                definite_codes.append("push_subscription_gone")
                break
            except DefiniteDeliveryError:
                _finish_open_deliveries(
                    run,
                    Delivery.Status.DEFINITELY_FAILED,
                    "delivery_definite",
                    now,
                    destination,
                )
                definite_codes.append("delivery_definite")
                break
            except AmbiguousDeliveryError:
                _finish_open_deliveries(
                    run,
                    Delivery.Status.NEEDS_REVIEW,
                    "delivery_ambiguous",
                    now,
                    destination,
                )
                ambiguous_codes.append("delivery_ambiguous")
                break
            except Exception:
                _finish_open_deliveries(
                    run,
                    Delivery.Status.NEEDS_REVIEW,
                    "delivery_unexpected",
                    now,
                    destination,
                )
                ambiguous_codes.append("delivery_unexpected")
                break

    if ambiguous_codes:
        return _finish_run(
            run, ScheduledRun.Status.NEEDS_REVIEW, now, ambiguous_codes[0]
        )
    if definite_codes:
        return _finish_run(run, ScheduledRun.Status.FAILED, now, definite_codes[0])
    return _finish_run(run, ScheduledRun.Status.SUCCEEDED, now)


def run_due_rules(
    now,
    claimed_runs=None,
    collector=collect_for_user,
    sender=send_to_destination,
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


def reconcile_interrupted_runs(
    now,
    collector=collect_for_user,
    sender=send_to_destination,
):
    runs = tuple(
        ScheduledRun.objects.filter(
            status__in=(
                ScheduledRun.Status.PENDING,
                ScheduledRun.Status.RUNNING,
                ScheduledRun.Status.INTERRUPTED,
            )
        ).order_by("id")
    )
    for run in runs:
        deliveries = tuple(run.deliveries.all())
        statuses = {delivery.status for delivery in deliveries}

        if statuses & {Delivery.Status.SENDING, Delivery.Status.NEEDS_REVIEW}:
            with transaction.atomic():
                _finish_open_deliveries(
                    run,
                    Delivery.Status.NEEDS_REVIEW,
                    "interrupted_sending",
                    now,
                )
                _finish_run(
                    run,
                    ScheduledRun.Status.NEEDS_REVIEW,
                    now,
                    "interrupted_sending",
                )
            continue

        if deliveries and statuses == {Delivery.Status.SUCCEEDED}:
            _finish_run(run, ScheduledRun.Status.SUCCEEDED, now)
            continue

        if Delivery.Status.DEFINITELY_FAILED in statuses:
            with transaction.atomic():
                _finish_open_deliveries(
                    run,
                    Delivery.Status.DEFINITELY_FAILED,
                    "interrupted_definite_failure",
                    now,
                )
                _finish_run(
                    run,
                    ScheduledRun.Status.FAILED,
                    now,
                    "interrupted_definite_failure",
                )
            continue

        if Delivery.Status.SUCCEEDED in statuses:
            with transaction.atomic():
                _finish_open_deliveries(
                    run,
                    Delivery.Status.NEEDS_REVIEW,
                    "interrupted_after_confirmation",
                    now,
                )
                _finish_run(
                    run,
                    ScheduledRun.Status.NEEDS_REVIEW,
                    now,
                    "interrupted_after_confirmation",
                )
            continue

        with transaction.atomic():
            run.deliveries.all().delete()
            run.course_results.all().delete()
            run.items.all().delete()
            ScheduledRun.objects.filter(pk=run.pk).update(
                status=ScheduledRun.Status.INTERRUPTED,
                safe_error_code="",
                finished_at=None,
            )
        run.status = ScheduledRun.Status.INTERRUPTED
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
