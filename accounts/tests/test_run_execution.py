from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.collection import AlertItem, CollectionResult, CourseOutcome
from accounts.models import Delivery, Destination, ScheduledRun
from accounts.notifications import AmbiguousDeliveryError, DefiniteDeliveryError
from accounts.scheduling import delivery_key, execute_run, run_due_rules
from accounts.services import encrypt_secret


KEY = Fernet.generate_key().decode()


@override_settings(CREDENTIAL_ENCRYPTION_KEYS=[KEY])
class RunExecutionTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
        self.user = self.create_ready_user("pilot@example.com", 123)
        self.other = self.create_ready_user("other@example.com", 456)
        self.sent_parts = []
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

    def create_ready_user(self, username, webhook_id):
        user = get_user_model().objects.create_user(username=username)
        Destination.objects.create(
            user=user,
            kind=Destination.Kind.DISCORD,
            encrypted_webhook_url=encrypt_secret(
                f"https://discord.com/api/webhooks/{webhook_id}/secret"
            ),
        )
        return user

    def create_run(self, *, user=None):
        return ScheduledRun.objects.create(
            user=user or self.user,
            scheduled_for=self.now,
        )

    def large_result_that_splits(self):
        return CollectionResult(
            (
                AlertItem(
                    101,
                    "전자회로",
                    "55",
                    "assignment",
                    "가" * 4000,
                    self.now + timedelta(days=1),
                    "unsubmitted",
                ),
            ),
            (CourseOutcome(101, "전자회로", "success"),),
        )

    def fail_if_called(self, *_args):
        self.fail("external boundary should not be called")

    def recording_sender(self, _kind, _url, part):
        self.sent_parts.append(part)
        return f"receipt-{len(self.sent_parts)}"

    def test_delivery_key_is_stable_and_part_scoped(self):
        run = self.create_run()

        self.assertEqual(delivery_key(run, 1, "part"), delivery_key(run, 1, "part"))
        self.assertNotEqual(delivery_key(run, 1, "part"), delivery_key(run, 2, "part"))

    def test_empty_success_finishes_without_delivery(self):
        run = self.create_run()
        result = CollectionResult((), (CourseOutcome(101, "A", "empty"),))

        execute_run(
            run,
            self.now,
            collector=lambda user, now: result,
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.EMPTY)
        self.assertFalse(run.deliveries.exists())
        self.assertEqual(run.course_results.get().status, "empty")

    def test_failures_without_items_still_send_warning(self):
        result = CollectionResult(
            (),
            (
                CourseOutcome(
                    101,
                    "A",
                    "failed",
                    "assignments_failed",
                    "과제 목록을 확인하지 못했습니다.",
                ),
            ),
        )
        run = self.create_run()

        execute_run(
            run,
            self.now,
            collector=lambda user, now: result,
            sender=self.recording_sender,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)
        self.assertEqual(len(self.sent_parts), 1)
        self.assertIn("조회 실패", self.sent_parts[0])

    def test_all_delivery_intents_exist_before_first_network_call(self):
        result = self.large_result_that_splits()
        run = self.create_run()
        observed_parts = []

        def sender(_kind, _url, part):
            rows = list(run.deliveries.all())
            self.assertGreater(len(rows), 1)
            if not observed_parts:
                self.assertEqual(rows[0].status, Delivery.Status.SENDING)
                self.assertTrue(
                    all(row.status == Delivery.Status.PENDING for row in rows[1:])
                )
            observed_parts.append(part)
            return f"receipt-{len(observed_parts)}"

        execute_run(
            run,
            self.now,
            collector=lambda user, now: result,
            sender=sender,
        )

        run.refresh_from_db()
        self.assertGreater(len(observed_parts), 1)
        self.assertEqual(run.status, ScheduledRun.Status.SUCCEEDED)
        self.assertTrue(
            all(
                row.status == Delivery.Status.SUCCEEDED
                for row in run.deliveries.all()
            )
        )

    def test_definite_first_part_failure_does_not_send_later_parts(self):
        run = self.create_run()
        calls = []

        def sender(_kind, _url, part):
            calls.append(part)
            raise DefiniteDeliveryError("secret provider body")

        execute_run(
            run,
            self.now,
            collector=lambda user, now: self.large_result_that_splits(),
            sender=sender,
        )

        run.refresh_from_db()
        self.assertEqual(len(calls), 1)
        self.assertEqual(run.status, ScheduledRun.Status.FAILED)
        self.assertTrue(
            all(
                row.status == Delivery.Status.DEFINITELY_FAILED
                for row in run.deliveries.all()
            )
        )
        self.assertNotIn("secret provider body", run.safe_error_code)

    def test_ambiguous_failure_becomes_needs_review_and_is_not_retried(self):
        run = self.create_run()
        calls = []

        def sender(_kind, _url, part):
            calls.append(part)
            raise AmbiguousDeliveryError("webhook-secret")

        execute_run(
            run,
            self.now,
            collector=lambda user, now: self.result,
            sender=sender,
        )
        execute_run(
            run,
            self.now,
            collector=lambda user, now: self.result,
            sender=sender,
        )

        run.refresh_from_db()
        self.assertEqual(len(calls), 1)
        self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)

    def test_unexpected_sender_failure_is_treated_as_ambiguous(self):
        run = self.create_run()

        execute_run(
            run,
            self.now,
            collector=lambda user, now: self.result,
            sender=lambda kind, url, part: (_ for _ in ()).throw(
                RuntimeError("provider secret")
            ),
        )

        run.refresh_from_db()
        delivery = run.deliveries.get()
        self.assertEqual(run.status, ScheduledRun.Status.NEEDS_REVIEW)
        self.assertEqual(delivery.status, Delivery.Status.NEEDS_REVIEW)
        self.assertEqual(delivery.safe_error_code, "delivery_unexpected")

    def test_missing_destination_fails_without_delivery(self):
        run = self.create_run()
        self.user.destination.delete()

        execute_run(
            run,
            self.now,
            collector=lambda user, now: self.result,
            sender=self.fail_if_called,
        )

        run.refresh_from_db()
        self.assertEqual(run.status, ScheduledRun.Status.FAILED)
        self.assertEqual(run.safe_error_code, "destination_missing")
        self.assertFalse(run.deliveries.exists())

    def test_one_users_failure_does_not_stop_next_claimed_user(self):
        runs = (self.create_run(user=self.user), self.create_run(user=self.other))

        def per_user_collector(user, _now):
            if user == self.user:
                raise RuntimeError("collector secret")
            return self.result

        run_due_rules(
            self.now,
            claimed_runs=runs,
            collector=per_user_collector,
            sender=self.recording_sender,
        )

        first = ScheduledRun.objects.get(user=self.user)
        second = ScheduledRun.objects.get(user=self.other)
        self.assertEqual(first.status, ScheduledRun.Status.FAILED)
        self.assertEqual(first.safe_error_code, "run_failed")
        self.assertEqual(second.status, ScheduledRun.Status.SUCCEEDED)
