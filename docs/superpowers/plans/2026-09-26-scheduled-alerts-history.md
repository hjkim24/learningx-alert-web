# Scheduled Alerts and History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run each configured user's assignment alert at one or two Asia/Seoul times, persist source and delivery outcomes, prevent duplicate sends for a scheduled slot, reconcile interrupted work without blind retries, and expose user-scoped run history.

**Architecture:** A long-running Django management command polls once per minute. Database uniqueness claims one `ScheduledRun` per user and UTC slot; the run service reuses the collection and one-attempt webhook interfaces from the preceding plan, persists delivery intent before I/O, and makes interruption state explicit. The web process only reads safe history rows and never performs scheduled delivery.

**Tech Stack:** Python 3.12, Django 5.2 LTS, SQLite transactions/constraints, `zoneinfo`, `hashlib`, Django management commands, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-25-learningx-alert-web-design.md`

## Global Constraints

- Execute only after `docs/superpowers/plans/2026-09-26-course-preview-test-notification.md` is complete on the same visible feature branch.
- Keep the existing one-web/one-worker/single-SQLite-host pilot architecture; do not add Celery, Redis, PostgreSQL, a queue, or Kubernetes.
- Poll once per minute and calculate configured times in `Asia/Seoul`; store canonical scheduled slots in UTC.
- Claim `(user, scheduled_for)` atomically and uniquely. Repeated scans of the same minute never create or send a second run.
- Re-fetch current assignment and submission state for every new scheduled run.
- Include only `now < due_at <= now + lookahead`; never infer failed completion checks as incomplete.
- Persist delivery intent before the network request. Change it to `sending` before calling the provider.
- A crash or connection ambiguity after `sending` becomes `needs_review` and is never automatically resent.
- A run interrupted before any delivery begins may be recollected and resumed for the same slot.
- No items and no collection failures means `empty` and sends nothing. Failures with no items still produce one warning message.
- Process pilot users sequentially and isolate each user's failures.
- Never log or render tokens, webhook URLs, provider bodies, authorization headers, or raw exception representations.
- Preserve all tests from the preceding plan plus the original 49 Django and 25 feasibility tests.

## Review Focus

- Two worker scans in the same configured minute must converge on one run and one set of delivery attempts; Tasks 1 and 2 test uniqueness and repeated scans.
- UTC/KST conversion at midnight and the exact minute comparison must select the correct local date without backfilling old slots; Task 2 uses literal boundary datetimes.
- A crash before any request must be resumable, while a crash after `sending` must become `needs_review` without another provider call; Task 4 tests both branches.
- Multi-part delivery must create all intent rows before the first request and must not send later parts after a definite or ambiguous first-part failure; Task 3 tests ordering and terminal statuses.
- A user must receive 404/empty results for another user's run ID, outcomes, items, and deliveries; Task 5 tests every history relation.

---

### Task 1: Add run, outcome, item, and delivery models

**Files:**
- Modify: `accounts/models.py`
- Create: `accounts/migrations/0003_scheduledrun_courserunresult_runitem_delivery.py`
- Create: `accounts/tests/test_run_models.py`

**Interfaces:**
- Consumes: Django user cascade and `Destination.Kind`.
- Produces: `ScheduledRun`, `CourseRunResult`, `RunItem`, and `Delivery` with status enums and uniqueness constraints.

- [ ] **Step 1: Write failing persistence tests**

Create `accounts/tests/test_run_models.py`:

```python
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

    def test_user_delete_cascades_every_run_record(self):
        run = self.create_run()
        CourseRunResult.objects.create(
            run=run,
            canvas_course_id=101,
            course_name="A",
            status="empty",
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
        self.assertFalse(Delivery.objects.exists())
```

- [ ] **Step 2: Run and verify missing-model failures**

Run: `.venv/bin/python manage.py test accounts.tests.test_run_models -v 2`

Expected: FAIL on imports for the four models.

- [ ] **Step 3: Implement models and database constraints**

Append these model shapes to `accounts/models.py`:

```python
class ScheduledRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        RUNNING = "running", "실행 중"
        SUCCEEDED = "succeeded", "성공"
        EMPTY = "empty", "보낼 항목 없음"
        FAILED = "failed", "실패"
        INTERRUPTED = "interrupted", "중단됨"
        NEEDS_REVIEW = "needs_review", "확인 필요"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheduled_runs")
    scheduled_for = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    safe_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "scheduled_for"), name="unique_user_scheduled_slot")
        ]
        ordering = ("-scheduled_for",)


class CourseRunResult(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "성공"
        EMPTY = "empty", "항목 없음"
        FAILED = "failed", "실패"

    run = models.ForeignKey(ScheduledRun, on_delete=models.CASCADE, related_name="course_results")
    canvas_course_id = models.BigIntegerField()
    course_name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices)
    error_code = models.CharField(max_length=64, blank=True)
    safe_summary = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("run", "canvas_course_id"), name="unique_run_course_result")
        ]


class RunItem(models.Model):
    run = models.ForeignKey(ScheduledRun, on_delete=models.CASCADE, related_name="items")
    canvas_course_id = models.BigIntegerField()
    external_id = models.CharField(max_length=128)
    item_type = models.CharField(max_length=32)
    title = models.CharField(max_length=500)
    due_at = models.DateTimeField()
    observed_state = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("run", "canvas_course_id", "external_id", "item_type", "due_at"),
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

    run = models.ForeignKey(ScheduledRun, on_delete=models.CASCADE, related_name="deliveries")
    destination_kind = models.CharField(max_length=16, choices=Destination.Kind.choices)
    part_number = models.PositiveSmallIntegerField()
    idempotency_key = models.CharField(max_length=64, unique=True)
    provider_confirmation_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    safe_error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("run", "part_number"), name="unique_run_delivery_part")
        ]
        ordering = ("part_number",)
```

Run: `.venv/bin/python manage.py makemigrations accounts`

Expected: creates migration `0003` with four tables and all uniqueness constraints.

- [ ] **Step 4: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_run_models -v 2`

Expected: PASS, 4 tests.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add accounts/models.py accounts/migrations/0003_scheduledrun_courserunresult_runitem_delivery.py accounts/tests/test_run_models.py
git commit -m "feat: add scheduled run history models"
```

### Task 2: Calculate and atomically claim due KST slots

**Files:**
- Create: `accounts/scheduling.py`
- Create: `accounts/tests/test_scheduling.py`

**Interfaces:**
- Consumes: `NotificationRule`, enabled assignment `CourseSelection`, configured `Destination`, and `ScheduledRun`.
- Produces: `matching_slot(rule, now) -> datetime | None` and `claim_due_runs(now) -> tuple[ScheduledRun, ...]`; the tuple ellipsis is Python's concrete variadic-tuple type syntax.

- [ ] **Step 1: Write failing timezone and idempotency tests**

Create `accounts/tests/test_scheduling.py` with literal UTC/KST expectations:

```python
def test_matching_slot_uses_seoul_local_date_across_utc_midnight(self):
    rule = NotificationRule(first_time=time(0, 5))
    now = datetime(2026, 9, 25, 15, 5, 37, tzinfo=UTC)
    self.assertEqual(
        matching_slot(rule, now),
        datetime(2026, 9, 25, 15, 5, tzinfo=UTC),
    )

def test_nonmatching_minute_does_not_backfill_earlier_slot(self):
    rule = NotificationRule(first_time=time(9, 0))
    now = datetime(2026, 9, 26, 0, 1, tzinfo=UTC)
    self.assertIsNone(matching_slot(rule, now))

def test_second_time_is_due_on_its_own_minute(self):
    rule = NotificationRule(first_time=time(9, 0), second_time=time(20, 0))
    now = datetime(2026, 9, 26, 11, 0, 12, tzinfo=UTC)
    self.assertEqual(matching_slot(rule, now), datetime(2026, 9, 26, 11, 0, tzinfo=UTC))

def test_repeated_scan_claims_one_run(self):
    self.make_ready_user(first_time=time(9, 0))
    now = datetime(2026, 9, 26, 0, 0, 45, tzinfo=UTC)
    first = claim_due_runs(now)
    second = claim_due_runs(now)
    self.assertEqual(len(first), 1)
    self.assertEqual(second, ())
    self.assertEqual(ScheduledRun.objects.count(), 1)

def test_unready_users_are_not_claimed(self):
    user_without_destination = self.make_user_with_rule_and_course()
    self.assertEqual(claim_due_runs(datetime(2026, 9, 26, 0, 0, tzinfo=UTC)), ())
    self.assertFalse(ScheduledRun.objects.filter(user=user_without_destination).exists())
```

- [ ] **Step 2: Run and verify missing scheduling module failure**

Run: `.venv/bin/python manage.py test accounts.tests.test_scheduling -v 2`

Expected: FAIL because `accounts.scheduling` does not exist.

- [ ] **Step 3: Implement exact-minute slot matching and claims**

Create `accounts/scheduling.py`:

```python
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
    rules = NotificationRule.objects.filter(
        user__destination__isnull=False,
        user__canvas_connection__isnull=False,
        user__course_selections__enabled=True,
        user__course_selections__include_assignments=True,
    ).select_related("user").distinct()
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
```

- [ ] **Step 4: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_scheduling -v 2`

Expected: PASS.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add accounts/scheduling.py accounts/tests/test_scheduling.py
git commit -m "feat: claim scheduled KST alert slots"
```

### Task 3: Execute runs with persisted delivery intent and no retries

**Files:**
- Modify: `accounts/scheduling.py`
- Create: `accounts/tests/test_run_execution.py`

**Interfaces:**
- Consumes: `collect_for_user`, `CollectionResult`, `render_notification`, `split_message`, `send_webhook_part`, `decrypt_secret`, and all Task 1 run models.
- Produces: `delivery_key(run, part_number, part) -> str`, `execute_run(run, now, collector=collect_for_user, sender=send_webhook_part) -> ScheduledRun`, and `run_due_rules(now, claimed_runs=None, collector=collect_for_user, sender=send_webhook_part)`.

- [ ] **Step 1: Write failing execution tests**

Create `accounts/tests/test_run_execution.py`. Use real database rows and small collector/sender callables. Add tests:

```python
def test_empty_success_finishes_without_delivery(self):
    run = self.create_run()
    execute_run(run, self.now, collector=lambda user, now: CollectionResult((), (CourseOutcome(101, "A", "empty"),)), sender=self.fail_if_called)
    run.refresh_from_db()
    self.assertEqual(run.status, ScheduledRun.Status.EMPTY)
    self.assertFalse(run.deliveries.exists())

def test_failures_without_items_still_send_warning(self):
    result = CollectionResult((), (CourseOutcome(101, "A", "failed", "assignments_failed", "과제 목록을 확인하지 못했습니다."),))
    run = self.create_run()
    execute_run(run, self.now, collector=lambda user, now: result, sender=self.recording_sender)
    self.assertEqual(len(self.sent_parts), 1)
    self.assertIn("조회 실패", self.sent_parts[0])

def test_all_delivery_intents_exist_before_first_network_call(self):
    result = self.large_result_that_splits()
    run = self.create_run()

    def sender(kind, url, part):
        self.assertGreater(run.deliveries.count(), 1)
        self.assertTrue(all(row.status == Delivery.Status.PENDING or row.part_number == 1 for row in run.deliveries.all()))
        return f"receipt-{len(self.sent_parts) + 1}"

    execute_run(run, self.now, collector=lambda user, now: result, sender=sender)

def test_definite_first_part_failure_does_not_send_later_parts(self):
    run = self.create_run()
    calls = []
    def sender(kind, url, part):
        calls.append(part)
        raise DefiniteDeliveryError("secret provider body")
    execute_run(run, self.now, collector=lambda user, now: self.large_result_that_splits(), sender=sender)
    self.assertEqual(len(calls), 1)
    self.assertEqual(run.deliveries.get(part_number=1).status, Delivery.Status.DEFINITELY_FAILED)
    self.assertTrue(all(row.status == Delivery.Status.DEFINITELY_FAILED for row in run.deliveries.filter(part_number__gt=1)))

def test_ambiguous_failure_becomes_needs_review_and_is_not_retried(self):
    run = self.create_run()
    calls = []
    def sender(kind, url, part):
        calls.append(part)
        raise AmbiguousDeliveryError("webhook-secret")
    execute_run(run, self.now, collector=lambda user, now: self.result, sender=sender)
    execute_run(run, self.now, collector=lambda user, now: self.result, sender=sender)
    run.refresh_from_db()
    self.assertEqual(len(calls), 1)
    self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)

def test_unexpected_sender_failure_is_treated_as_ambiguous(self):
    run = self.create_run()
    execute_run(
        run,
        self.now,
        collector=lambda user, now: self.result,
        sender=lambda kind, url, part: (_ for _ in ()).throw(RuntimeError("provider secret")),
    )
    run.refresh_from_db()
    self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
    self.assertEqual(run.deliveries.get().status, Delivery.Status.NEEDS_REVIEW)

def test_one_users_failure_does_not_stop_next_claimed_user(self):
    runs = (self.create_run(user=self.user), self.create_run(user=self.other))
    run_due_rules(self.now, claimed_runs=runs, collector=self.per_user_collector, sender=self.recording_sender)
    self.assertEqual(ScheduledRun.objects.get(user=self.user).status, ScheduledRun.Status.FAILED)
    self.assertEqual(ScheduledRun.objects.get(user=self.other).status, ScheduledRun.Status.SUCCEEDED)
```

The collector and sender doubles represent external boundaries; assertions target persisted real model state and rendered content.

- [ ] **Step 2: Run and verify the missing functions fail**

Run: `.venv/bin/python manage.py test accounts.tests.test_run_execution -v 2`

Expected: FAIL because `execute_run`, `delivery_key`, and `run_due_rules` do not exist.

- [ ] **Step 3: Implement idempotent run execution**

Extend `accounts/scheduling.py` with these rules:

```python
def delivery_key(run, part_number, part):
    part_hash = hashlib.sha256(part.encode()).hexdigest()
    identity = f"{run.user_id}:{run.scheduled_for.isoformat()}:{part_number}:{part_hash}"
    return hashlib.sha256(identity.encode()).hexdigest()
```

`execute_run` must:

1. Return immediately for terminal `succeeded`, `empty`, `failed`, or `needs_review` runs.
2. Mark the run `running` and set `started_at` before collection.
3. Call the collector with the run user and supplied `now`; replace only this run's outcome/item rows in a transaction.
4. Persist each `CourseOutcome` and `AlertItem` without raw external payloads.
5. Mark `empty` and return when no items and no failed outcomes exist.
6. Fail safely with `destination_missing` if the current user destination disappeared before execution.
7. Render and split the message, then create every `Delivery(PENDING)` before any provider request.
8. Decrypt the destination URL only immediately before the delivery loop and mark it with `@sensitive_variables`.
9. For each part, atomically change `pending -> sending` and set `started_at`, then call the sender exactly once.
10. On receipt, set `succeeded`, confirmation ID, and `finished_at`.
11. On `DefiniteDeliveryError`, set the current and remaining unsent parts to `definitely_failed`, use safe codes only, mark the run `failed`, and stop.
12. On `AmbiguousDeliveryError`, set the current and remaining unsent parts to `needs_review`, mark the run `needs_review`, and stop.
13. Treat any other exception raised after a delivery enters `sending` as ambiguous: use safe code `delivery_unexpected`, mark current/remaining parts and the run `needs_review`, and never expose or retry the exception.
14. Mark the run `succeeded` only if all parts have provider confirmation.

Wrap unexpected pre-delivery exceptions per run in `run_due_rules`: mark only that run `failed` with `run_failed`, do not use `repr(error)`, and continue to the next run. Accept an optional `claimed_runs` tuple for deterministic tests; otherwise call `claim_due_runs(now)`.

- [ ] **Step 4: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_run_execution -v 2`

Expected: PASS, including intent ordering, stop-after-failure, and no-retry assertions.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add accounts/scheduling.py accounts/tests/test_run_execution.py
git commit -m "feat: execute idempotent scheduled alerts"
```

### Task 4: Reconcile interrupted runs and add the worker command

**Files:**
- Modify: `accounts/scheduling.py`
- Create: `accounts/management/__init__.py`
- Create: `accounts/management/commands/__init__.py`
- Create: `accounts/management/commands/run_scheduler.py`
- Create: `accounts/tests/test_worker.py`

**Interfaces:**
- Consumes: `execute_run`, `run_due_rules`, persisted run/delivery statuses.
- Produces: `reconcile_interrupted_runs(now, collector=collect_for_user, sender=send_webhook_part)` and `python manage.py run_scheduler [--once]`.

- [ ] **Step 1: Write failing interruption tests**

Create `accounts/tests/test_worker.py` and assert real database transitions:

```python
def test_running_without_started_delivery_is_recollected_and_resumed(self):
    run = self.create_running_run()
    Delivery.objects.create(
        run=run,
        destination_kind="discord",
        part_number=1,
        idempotency_key="pending-key",
    )
    calls = []
    reconcile_interrupted_runs(self.now, collector=self.collector(calls), sender=self.sender)
    run.refresh_from_db()
    self.assertEqual(calls, [self.user.pk])
    self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)

def test_sending_delivery_becomes_needs_review_without_provider_call(self):
    run = self.create_running_run()
    Delivery.objects.create(
        run=run,
        destination_kind="discord",
        part_number=1,
        idempotency_key="sending-key",
        status=Delivery.Status.SENDING,
    )
    calls = []
    reconcile_interrupted_runs(self.now, collector=self.collector(calls), sender=self.sender)
    run.refresh_from_db()
    self.assertEqual(calls, [])
    self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
    self.assertEqual(run.deliveries.get().status, Delivery.Status.NEEDS_REVIEW)

def test_all_confirmed_parts_finish_crashed_run_without_resend(self):
    run = self.create_running_run()
    Delivery.objects.create(
        run=run,
        destination_kind="discord",
        part_number=1,
        idempotency_key="success-key",
        status=Delivery.Status.SUCCEEDED,
        provider_confirmation_id="message-1",
    )
    reconcile_interrupted_runs(self.now, collector=self.fail_if_called, sender=self.fail_if_called)
    run.refresh_from_db()
    self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)

@patch("accounts.management.commands.run_scheduler.run_due_rules")
@patch("accounts.management.commands.run_scheduler.reconcile_interrupted_runs")
def test_once_reconciles_then_scans_once(self, reconcile, scan):
    call_command("run_scheduler", "--once")
    self.assertTrue(reconcile.called)
    self.assertTrue(scan.called)
```

- [ ] **Step 2: Run and verify missing command/reconciler failures**

Run: `.venv/bin/python manage.py test accounts.tests.test_worker -v 2`

Expected: FAIL because the reconciler and management command do not exist.

- [ ] **Step 3: Implement startup reconciliation**

`reconcile_interrupted_runs` processes every `RUNNING` run independently:

- if any delivery is `sending`, atomically mark it and all remaining pending parts `needs_review`, then mark the run `needs_review`;
- if at least one delivery exists and all existing deliveries are `succeeded`, mark the run `succeeded` without I/O;
- if any existing delivery is `definitely_failed`, mark the run `failed` without I/O;
- otherwise, no request started: delete pending intents and persisted collection snapshots for only that run, mark it `interrupted`, and call `execute_run` to recollect/resume safely.

Never reconsider terminal runs.

- [ ] **Step 4: Implement the once-per-minute worker**

Create `run_scheduler.py` with `--once`. On startup call `reconcile_interrupted_runs(timezone.now())`, then call `run_due_rules(timezone.now())`. In continuous mode, calculate the seconds to the next UTC minute boundary with `time.time()` and sleep at most 60 seconds; do not busy-wait. Log only run/user IDs, safe codes, and counts.

The command must catch `KeyboardInterrupt` for a clean exit but must not swallow programming errors at module import or configuration startup.

- [ ] **Step 5: Run focused and full tests**

Run: `.venv/bin/python manage.py test accounts.tests.test_worker -v 2`

Expected: PASS.

Run: `.venv/bin/python manage.py test && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add accounts/scheduling.py accounts/management accounts/tests/test_worker.py
git commit -m "feat: add resilient scheduler worker"
```

### Task 5: Expose safe history, next-run status, and account deletion

**Files:**
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Modify: `templates/accounts/dashboard.html`
- Create: `templates/accounts/run_detail.html`
- Modify: `static/app.css`
- Modify: `README.md`
- Create: `accounts/tests/test_run_history.py`
- Create: `accounts/tests/test_account_deletion.py`

**Interfaces:**
- Consumes: `matching_slot` semantics, run models, and all user-owned configuration.
- Produces: safe recent-run dashboard data, authenticated `run_detail`, POST-only `account_delete`, and local worker documentation.

- [ ] **Step 1: Write failing history and deletion tests**

In `accounts/tests/test_run_history.py`, create two users with fully populated runs. Assert:

```python
def test_run_detail_contains_only_current_users_safe_snapshots(self):
    self.client.force_login(self.user)
    response = self.client.get(reverse("run_detail", args=(self.own_run.pk,)))
    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "내 과제")
    self.assertContains(response, "assignments_failed")
    self.assertNotContains(response, "ciphertext-sentinel")
    self.assertNotContains(response, "webhook-sentinel")

def test_other_users_run_is_404(self):
    self.client.force_login(self.user)
    response = self.client.get(reverse("run_detail", args=(self.other_run.pk,)))
    self.assertEqual(response.status_code, 404)

def test_dashboard_shows_recent_run_and_truthful_next_schedule(self):
    self.client.force_login(self.user)
    response = self.client.get(reverse("dashboard"))
    self.assertContains(response, "최근 실행")
    self.assertContains(response, "다음 예약")
```

In `accounts/tests/test_account_deletion.py`, assert login/POST/CSRF requirements, current-user deletion, complete cascade of connection/config/run data, preservation of the other user, logout, and external revocation guidance before deletion.

- [ ] **Step 2: Run and verify route/template failures**

Run: `.venv/bin/python manage.py test accounts.tests.test_run_history accounts.tests.test_account_deletion -v 2`

Expected: FAIL because the routes and run template do not exist.

- [ ] **Step 3: Implement strictly scoped history views**

Add:

```python
@login_required
def run_detail(request, pk):
    run = get_object_or_404(
        ScheduledRun.objects.prefetch_related("course_results", "items", "deliveries"),
        pk=pk,
        user=request.user,
    )
    return render(request, "accounts/run_detail.html", {"run": run})
```

Extend `dashboard` using only `.filter(user=request.user)` and safe selected fields. Calculate the next configured KST time without creating a run. Render recent run status, safe course failures, destination problems, and links to the current user's detail page.

Add POST-only `account_delete`: store the authenticated user, call `logout(request)`, delete the user, and redirect to login with no secret-bearing message. The dashboard must explain external Canvas token and webhook revocation before the destructive form.

Register:

```python
path("runs/<int:pk>/", views.run_detail, name="run_detail"),
path("account/delete/", views.account_delete, name="account_delete"),
```

- [ ] **Step 4: Finish templates, CSS, and runbook**

Create `run_detail.html` with scheduled/start/finish status, sorted items, per-course result, and per-part delivery status. Render only safe codes/summaries and confirmation IDs; never ciphertext.

Update `README.md` with separate local processes:

```bash
.venv/bin/python manage.py runserver
.venv/bin/python manage.py run_scheduler
```

Document `run_scheduler --once` as an operator/test command, no automatic retries, and the meanings of `definitely_failed` versus `needs_review`. Do not describe OCI deployment as complete.

- [ ] **Step 5: Run complete verification**

Run: `.venv/bin/python manage.py test`

Expected: PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: PASS, 25 feasibility tests.

Run: `.venv/bin/python manage.py check && .venv/bin/python manage.py makemigrations --check --dry-run && git diff --check`

Expected: no issues, no missing migrations, and no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add accounts/views.py accounts/urls.py templates/accounts/dashboard.html templates/accounts/run_detail.html static/app.css README.md accounts/tests/test_run_history.py accounts/tests/test_account_deletion.py
git commit -m "feat: add alert history and account cleanup"
```

## Self-review record

- Spec coverage: KST scheduling, slot uniqueness, fresh collection, empty/failure distinction, persisted delivery intent, provider confirmation, interruption reconciliation, history, user isolation, and cascading account deletion are assigned to Tasks 1–5.
- Placeholder scan: code examples use complete literals and named helpers defined in their owning task; prose specifies exact state transitions where copying a partial implementation would be misleading.
- Type consistency: `CollectionResult`, `CourseOutcome`, `render_notification`, `split_message`, and `send_webhook_part` are produced by the preceding plan and consumed unchanged here.
- Review Focus: each listed scheduler/interruption/isolation risk maps to explicit tests above.
