from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.models import Delivery, Destination, ScheduledRun
from accounts.scheduling import reconcile_interrupted_runs
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class WorkerTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 1, tzinfo=UTC)
        self.user = get_user_model().objects.create_user(username="pilot@example.com")
        Destination.objects.create(
            user=self.user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(
                "https://discord.com/api/webhooks/123/secret"
            ),
        )
        self.result = CollectionResult(
            (
                AlertItem(
                    101,
                    "전자회로",
                    "55",
                    "assignment",
                    "HW",
                    self.now + timedelta(days=1),
                    "unsubmitted",
                ),
            ),
            (CourseOutcome(101, "전자회로", "success"),),
        )

    def create_running_run(self):
        return ScheduledRun.objects.create(
            user=self.user,
            scheduled_for=self.now.replace(second=0),
            status=ScheduledRun.Status.RUNNING,
            started_at=self.now - timedelta(minutes=1),
        )

    def collector(self, calls):
        def collect(user, _now):
            calls.append(user.pk)
            return self.result

        return collect

    def sender(self, _kind, _url, _part):
        return "message-1"

    def fail_if_called(self, *_args):
        self.fail("external boundary should not be called")

    def test_running_without_started_delivery_is_recollected_and_resumed(self):
        run = self.create_running_run()
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key="pending-key",
        )
        calls = []

        reconcile_interrupted_runs(
            self.now,
            collector=self.collector(calls),
            sender=self.sender,
        )

        run.refresh_from_db()
        self.assertEqual(calls, [self.user.pk])
        self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)
        self.assertFalse(run.deliveries.filter(idempotency_key="pending-key").exists())

    def test_sending_delivery_becomes_needs_review_without_provider_call(self):
        run = self.create_running_run()
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key="sending-key",
            status=Delivery.Status.SENDING,
        )
        calls = []

        reconcile_interrupted_runs(
            self.now,
            collector=self.collector(calls),
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        self.assertEqual(calls, [])
        self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
        self.assertEqual(run.deliveries.get().status, Delivery.Status.NEEDS_REVIEW)

    def test_all_confirmed_parts_finish_crashed_run_without_resend(self):
        run = self.create_running_run()
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key="success-key",
            status=Delivery.Status.SUCCEEDED,
            provider_confirmation_id="message-1",
        )

        reconcile_interrupted_runs(
            self.now,
            collector=self.fail_if_called,
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)

    def test_definite_failure_finishes_crashed_run_without_resend(self):
        run = self.create_running_run()
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key="failed-key",
            status=Delivery.Status.DEFINITELY_FAILED,
        )

        reconcile_interrupted_runs(
            self.now,
            collector=self.fail_if_called,
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.FAILED)

    def test_confirmed_and_pending_parts_require_review_without_resend(self):
        run = self.create_running_run()
        Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=1,
            idempotency_key="success-key",
            status=Delivery.Status.SUCCEEDED,
            provider_confirmation_id="message-1",
        )
        pending = Delivery.objects.create(
            run=run,
            destination_kind=Destination.Kind.DISCORD,
            part_number=2,
            idempotency_key="pending-key",
        )

        reconcile_interrupted_runs(
            self.now,
            collector=self.fail_if_called,
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
        self.assertEqual(pending.status, Delivery.Status.NEEDS_REVIEW)

    @patch("accounts.management.commands.run_scheduler.run_due_rules")
    @patch("accounts.management.commands.run_scheduler.reconcile_interrupted_runs")
    def test_once_reconciles_then_scans_once(self, reconcile, scan):
        calls = []
        reconcile.side_effect = lambda now: calls.append("reconcile")
        scan.side_effect = lambda now: calls.append("scan") or ()

        call_command("run_scheduler", "--once")

        self.assertEqual(calls, ["reconcile", "scan"])

    @patch("accounts.management.commands.run_scheduler.time.sleep")
    @patch("accounts.management.commands.run_scheduler.time.time", return_value=90.25)
    @patch(
        "accounts.management.commands.run_scheduler.run_due_rules",
        side_effect=((), KeyboardInterrupt),
    )
    @patch("accounts.management.commands.run_scheduler.reconcile_interrupted_runs")
    def test_continuous_worker_sleeps_to_next_minute(
        self,
        _reconcile,
        _scan,
        _clock,
        sleep,
    ):
        call_command("run_scheduler")

        sleep.assert_called_once_with(29.75)

    @patch(
        "accounts.management.commands.run_scheduler.reconcile_interrupted_runs",
        side_effect=RuntimeError("configuration failure"),
    )
    def test_startup_programming_error_is_not_swallowed(self, _reconcile):
        with self.assertRaises(RuntimeError):
            call_command("run_scheduler", "--once")
