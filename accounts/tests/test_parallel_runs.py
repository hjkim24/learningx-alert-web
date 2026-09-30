import threading
import time
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase, override_settings

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.models import Delivery, Destination, ScheduledRun
from accounts.scheduling import run_due_rules
from accounts.services import encrypt_secret

KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY], SCHEDULER_CONCURRENCY=4)
class RunPoolTestBase(TransactionTestCase):
    """The threaded path commits for real, so it cannot live in a TestCase."""

    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.lock = threading.Lock()
        self.threads = set()
        self.active = 0
        self.peak = 0
        self.runs = []
        for index in range(6):
            user = get_user_model().objects.create_user(username=f"user{index}@example.com")
            Destination.objects.create(
                user=user,
                kind=Destination.Kind.DISCORD,
                encrypted_webhook_url=encrypt_secret(
                    f"https://discord.com/api/webhooks/{index}/secret"
                ),
            )
            self.runs.append(ScheduledRun.objects.create(user=user, scheduled_for=self.now))

    def slow_collector(self, user, now):
        with self.lock:
            self.threads.add(threading.get_ident())
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.2)
        with self.lock:
            self.active -= 1
        return CollectionResult(
            (
                AlertItem(
                    101, "전자회로", "55", "assignment", f"HW {user.pk}",
                    now + timedelta(days=1), "unsubmitted",
                ),
            ),
            (CourseOutcome(101, "전자회로", "success"),),
        )

    def run_all(self, collector=None):
        run_due_rules(
            self.now,
            claimed_runs=self.runs,
            collector=collector or self.slow_collector,
            sender=lambda _kind, _url, _part: "receipt",
        )


@skipUnless(connection.vendor == "sqlite", "SQLite fallback only")
class SqliteStaysSerialTests(RunPoolTestBase):
    def test_sqlite_runs_one_at_a_time_and_all_finish(self):
        self.run_all()

        self.assertEqual(self.peak, 1)
        self.assertEqual(
            set(ScheduledRun.objects.values_list("status", flat=True)),
            {ScheduledRun.Status.SUCCEEDED},
        )


@skipUnless(connection.vendor == "mysql", "threads need a real multi-writer DB")
class ParallelRunTests(RunPoolTestBase):
    def test_runs_overlap_up_to_the_limit_and_all_finish(self):
        started = time.monotonic()
        run_due_rules(
            self.now,
            claimed_runs=self.runs,
            collector=self.slow_collector,
            sender=lambda _kind, _url, _part: "receipt",
        )
        elapsed = time.monotonic() - started

        self.assertEqual(self.peak, 4)  # never more than SCHEDULER_CONCURRENCY
        self.assertGreater(len(self.threads), 1)
        self.assertLess(elapsed, 6 * 0.2)  # serial would take >= 1.2s
        statuses = set(ScheduledRun.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {ScheduledRun.Status.SUCCEEDED})
        self.assertEqual(
            Delivery.objects.filter(status=Delivery.Status.SUCCEEDED).count(), 6
        )

    def test_one_crashing_run_does_not_stop_the_others(self):
        crash_user = self.runs[0].user_id

        def collector(user, now):
            if user.pk == crash_user:
                raise RuntimeError("boom")
            return self.slow_collector(user, now)

        with self.assertLogs("accounts.scheduling", level="ERROR"):
            run_due_rules(
                self.now,
                claimed_runs=self.runs,
                collector=collector,
                sender=lambda _kind, _url, _part: "receipt",
            )

        self.assertEqual(
            ScheduledRun.objects.get(pk=self.runs[0].pk).status, ScheduledRun.Status.FAILED
        )
        self.assertEqual(
            ScheduledRun.objects.filter(status=ScheduledRun.Status.SUCCEEDED).count(), 5
        )
