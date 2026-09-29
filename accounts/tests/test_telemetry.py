import json
import logging
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts import scheduling, telemetry
from accounts.models import CourseRunResult, Delivery, ScheduledRun
from config.logging import JsonFormatter, RedactingFilter, redact


class RedactionTests(SimpleTestCase):
    def test_secrets_are_masked(self):
        cases = {
            "post https://discord.com/api/webhooks/123/abcDEF-secret failed":
                "post https://discord.com/[redacted] failed",
            "https://hooks.slack.com/services/T0/B0/xyz": "https://hooks.slack.com/[redacted]",
            "push https://jmt17.google.com/fcm/send/abc:def": "push https://jmt17.google.com/[redacted]",
            "Authorization: Bearer 1234~abcdefghijklmnopqrstuvwxyz": "Authorization: Bearer [redacted]",
            "token 12345~AbCdEfGhIjKlMnOpQrStUvWxYz0123 leaked": "token [redacted-token] leaked",
            "user someone@g.skku.edu logged in": "user [redacted-email] logged in",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), expected)

    def test_canvas_host_is_kept(self):
        text = "GET https://canvas.skku.edu/api/v1/courses 404"
        self.assertEqual(redact(text), text)

    def test_filter_masks_formatted_args(self):
        record = logging.LogRecord(
            "x", logging.INFO, __file__, 1, "sent to %s", ("https://discord.com/api/webhooks/1/s",), None
        )
        RedactingFilter().filter(record)
        self.assertEqual(record.getMessage(), "sent to https://discord.com/[redacted]")


class JsonFormatterTests(SimpleTestCase):
    def test_exception_message_is_not_logged(self):
        try:
            raise RuntimeError("token 1~secretsecretsecretsecretsecret")
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                "accounts", logging.ERROR, __file__, 1, "boom", (), sys.exc_info()
            )
        record.run_id = 7
        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["exc_type"], "RuntimeError")
        self.assertEqual(payload["run_id"], 7)
        self.assertNotIn("secret", payload["stack"])
        self.assertIn("test_telemetry.py", payload["stack"])


class RunTelemetryTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="metrics@example.com")
        now = timezone.now()
        self.run = ScheduledRun.objects.create(
            user=user,
            scheduled_for=now - timedelta(seconds=30),
            status=ScheduledRun.Status.RUNNING,
            started_at=now,
        )
        CourseRunResult.objects.create(
            run=self.run, canvas_course_id=1, course_name="A", status="success"
        )
        CourseRunResult.objects.create(
            run=self.run, canvas_course_id=2, course_name="B", status="failed",
            error_code="lectures_failed",
        )
        Delivery.objects.create(
            run=self.run, destination_kind="slack", part_number=1, idempotency_key="k1",
            status=Delivery.Status.SUCCEEDED,
        )

    def test_finished_run_records_metrics_without_personal_attributes(self):
        with mock.patch.object(telemetry, "runs") as runs, \
                mock.patch.object(telemetry, "run_delay") as delay, \
                mock.patch.object(telemetry, "deliveries") as deliveries, \
                mock.patch.object(telemetry, "course_results") as courses, \
                self.assertLogs("accounts.scheduling", level="INFO") as logs:
            scheduling._finish_run(self.run, ScheduledRun.Status.FAILED, timezone.now(), "x")

        runs.add.assert_called_once_with(1, {"status": "failed"})
        self.assertAlmostEqual(delay.record.call_args.args[0], 30, delta=1)
        deliveries.add.assert_called_once_with(1, {"kind": "slack", "status": "succeeded"})
        self.assertEqual(
            sorted(call.args[1]["error_code"] for call in courses.add.call_args_list),
            ["lectures_failed", "none"],
        )
        for call in runs.add.call_args_list + deliveries.add.call_args_list + courses.add.call_args_list:
            self.assertFalse({"user", "user_id", "run_id", "course"} & set(call.args[1]))
        self.assertIn("WARNING:accounts.scheduling:run finished", logs.output[0])

    def test_metrics_are_off_without_endpoint(self):
        with mock.patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": ""}):
            self.assertFalse(telemetry.configure_metrics("test"))
