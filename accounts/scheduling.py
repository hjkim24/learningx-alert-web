import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, connections, transaction
from django.db.models import Count
from opentelemetry import trace
from django.views.decorators.debug import sensitive_variables

from . import telemetry
from .collection import alert_selection_filter, collect_for_user
from .models import (
    CanvasConnection,
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
logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("learningx_alert.scheduler")
_ATTENTION_STATUSES = {
    ScheduledRun.Status.FAILED,
    ScheduledRun.Status.NEEDS_REVIEW,
    ScheduledRun.Status.INTERRUPTED,
}


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


# How far back one scan looks for alarm minutes it has not seen yet: after a
# scan longer than a minute, or a restart (deploy, crash) at an alarm time.
CATCH_UP_MINUTES = 15


def slot_minutes(now, since=None):
    """Alarm minutes to check: every minute in (since, now], at most
    CATCH_UP_MINUTES back. ``since=None`` means just the current minute."""
    current = now.replace(second=0, microsecond=0)
    if since is None:
        return [current]
    earliest = max(
        since.replace(second=0, microsecond=0) + timedelta(minutes=1),
        current - timedelta(minutes=CATCH_UP_MINUTES),
    )
    minutes = []
    minute = earliest
    while minute <= current:
        minutes.append(minute)
        minute += timedelta(minutes=1)
    return minutes or [current]


def claim_due_runs(now, since=None):
    """Create a ScheduledRun for every alarm due in slot_minutes(now, since).

    The (user, scheduled_for) unique constraint makes this idempotent, so
    looking back over minutes an earlier scan already claimed is harmless.
    """
    minutes = slot_minutes(now, since)
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
    current = minutes[-1]
    for rule in rules:
        slots = {slot for slot in (matching_slot(rule, minute) for minute in minutes) if slot}
        for slot in sorted(slots):
            try:
                with transaction.atomic():
                    run, created = ScheduledRun.objects.get_or_create(
                        user=rule.user,
                        scheduled_for=slot,
                    )
            except IntegrityError:
                continue
            if not created:
                continue
            claimed.append(run)
            if slot < current:
                logger.warning(
                    "late slot claimed",
                    extra={
                        "event": "late_slot_claimed",
                        "run_id": run.pk,
                        "delay_seconds": (current - slot).total_seconds(),
                    },
                )
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
    _record_finished_run(run)
    return run


def _record_finished_run(run):
    """Metrics + one log line per finished run. Never lets telemetry break a run."""
    try:
        delay = None
        if run.started_at and run.scheduled_for:
            delay = max(0.0, (run.started_at - run.scheduled_for).total_seconds())
            telemetry.run_delay.record(delay)
        telemetry.runs.add(1, {"status": run.status})

        delivery_counts = {}
        for row in (
            Delivery.objects.filter(run_id=run.pk)
            .values("destination_kind", "status")
            .annotate(count=Count("id"))
        ):
            telemetry.deliveries.add(
                row["count"], {"kind": row["destination_kind"], "status": row["status"]}
            )
            key = f"{row['destination_kind']}:{row['status']}"
            delivery_counts[key] = row["count"]

        course_counts = {}
        for row in (
            CourseRunResult.objects.filter(run_id=run.pk)
            .values("status", "error_code")
            .annotate(count=Count("id"))
        ):
            telemetry.course_results.add(
                row["count"],
                {"status": row["status"], "error_code": row["error_code"] or "none"},
            )
            key = row["status"] + (f":{row['error_code']}" if row["error_code"] else "")
            course_counts[key] = row["count"]

        level = logging.WARNING if run.status in _ATTENTION_STATUSES else logging.INFO
        logger.log(
            level,
            "run finished",
            extra={
                "event": "run_finished",
                "run_id": run.pk,
                "status": run.status,
                "safe_error_code": run.safe_error_code,
                "delay_seconds": delay,
                "deliveries": delivery_counts,
                "courses": course_counts,
            },
        )
    except Exception:  # pragma: no cover - defensive; telemetry must not fail a run
        logger.exception("run telemetry failed", extra={"event": "telemetry_error"})


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


def _empty_notice_due(run):
    """Whether this empty run should still send the short "nothing due" note.

    Only when the user turned it on, has somewhere to send it, and no earlier
    run on the same KST day already sent one (an empty run that delivered).
    """
    rule = NotificationRule.objects.filter(user_id=run.user_id).only("notify_when_empty").first()
    if rule is None or not rule.notify_when_empty:
        return False
    if not Destination.objects.filter(user_id=run.user_id).exists():
        return False
    day = (run.scheduled_for or datetime.now(UTC)).astimezone(SEOUL).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=SEOUL)
    return not (
        ScheduledRun.objects.filter(
            user_id=run.user_id,
            scheduled_for__gte=start,
            scheduled_for__lt=start + timedelta(days=1),
            status=ScheduledRun.Status.SUCCEEDED,
            items__isnull=True,
            deliveries__status=Delivery.Status.SUCCEEDED,
        )
        .exclude(pk=run.pk)
        .exists()
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
    if not result.items and not has_failures and not _empty_notice_due(run):
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
    since=None,
):
    runs = claim_due_runs(now, since) if claimed_runs is None else claimed_runs
    scan_clock = time.monotonic()
    if runs:
        _safe_record(telemetry.scan_batch, len(runs))
    workers = max(1, min(settings.SCHEDULER_CONCURRENCY, len(runs)))
    if connections["default"].vendor == "sqlite":
        # SQLite locks the whole database per write; parallel runs would fail
        # with "database is locked". Only the MySQL deployment runs threads.
        workers = 1
    schools = _run_schools(runs)
    if workers == 1:
        for run in runs:
            _run_one(run, now, collector, sender, schools.get(run.user_id))
    else:
        # Runs are I/O-bound (Canvas, push services), so threads overlap the
        # waiting. Each run belongs to a different user, so they share no rows;
        # the pool size also caps concurrent Canvas traffic at `workers` users.
        # A per-school gate keeps one slow Canvas from holding every thread;
        # interleaving by school keeps the other threads busy meanwhile.
        gates = {
            code: threading.BoundedSemaphore(settings.SCHOOL_CONCURRENCY)
            for code in set(schools.values())
        }
        ordered = _interleave_by_school(runs, schools)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="run") as pool:
            for future in [
                pool.submit(
                    _run_in_thread,
                    run,
                    now,
                    collector,
                    sender,
                    schools.get(run.user_id),
                    gates.get(schools.get(run.user_id)),
                )
                for run in ordered
            ]:
                future.result()
    if runs:
        _safe_record(telemetry.scan_duration, time.monotonic() - scan_clock)
    return runs


def _run_schools(runs):
    """user_id -> school code for the users behind ``runs``."""
    if not runs:
        return {}
    return dict(
        CanvasConnection.objects.filter(
            user_id__in={run.user_id for run in runs}
        ).values_list("user_id", "school")
    )


def _interleave_by_school(runs, schools):
    queues = {}
    for run in runs:
        queues.setdefault(schools.get(run.user_id), []).append(run)
    ordered = []
    while any(queues.values()):
        for queue in queues.values():
            if queue:
                ordered.append(queue.pop(0))
    return ordered


def _run_in_thread(run, now, collector, sender, school=None, gate=None):
    try:
        if gate is None:
            _run_one(run, now, collector, sender, school)
        else:
            with gate:
                _run_one(run, now, collector, sender, school)
    finally:
        # Django opens one DB connection per thread; release this worker's.
        connections.close_all()


def _run_one(run, now, collector, sender, school=None):
    run_clock = time.monotonic()
    school_attrs = {"school": school or "none"}
    if run.scheduled_for:
        _safe_record(
            telemetry.run_actual_delay,
            max(0.0, (datetime.now(UTC) - run.scheduled_for).total_seconds()),
            school_attrs,
        )
    try:
        # One trace per run: Canvas/LearningX/webhook calls and DB queries
        # nest under it. Only the run id and final status are attached.
        with _tracer.start_as_current_span(
            "scheduled_run", attributes={"learningx.run_id": run.pk}
        ) as span:
            execute_run(run, now, collector=collector, sender=sender)
            span.set_attribute("learningx.run_status", str(run.status))
    except Exception:
        logger.exception("run crashed", extra={"event": "run_crashed", "run_id": run.pk})
        try:
            _finish_run(
                run,
                ScheduledRun.Status.FAILED,
                now,
                "run_failed",
            )
        except Exception:
            # Left RUNNING; reconcile_interrupted_runs settles it on restart.
            logger.exception("run finish failed", extra={"event": "run_finish_failed", "run_id": run.pk})
    _safe_record(telemetry.run_duration, time.monotonic() - run_clock, school_attrs)


def _safe_record(instrument, value, attributes=None):
    try:
        if attributes:
            instrument.record(value, attributes)
        else:
            instrument.record(value)
    except Exception:  # telemetry must never break a run
        pass


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
