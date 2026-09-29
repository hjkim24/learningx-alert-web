from types import SimpleNamespace
from unittest import mock
from urllib.request import Request

from django.test import SimpleTestCase
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from accounts import telemetry
from learningx_alert import network


class OutboundSpanTests(SimpleTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        patcher = mock.patch.object(network, "_tracer", provider.get_tracer("test"))
        patcher.start()
        self.addCleanup(patcher.stop)
        resolve = mock.patch.object(network, "resolve_public_addresses", return_value=("203.0.113.5",))
        resolve.start()
        self.addCleanup(resolve.stop)

    def _open(self, url, response=None, error=None):
        handler = network.PinnedHTTPSHandler()
        with mock.patch.object(handler, "do_open", side_effect=error, return_value=response):
            return handler.https_open(Request(url, method="POST"))

    def test_span_keeps_host_but_not_the_secret_path(self):
        self._open(
            "https://discord.com/api/webhooks/123/very-secret-token?wait=true",
            response=SimpleNamespace(status=204),
        )
        (span,) = self.exporter.get_finished_spans()
        self.assertEqual(span.name, "HTTPS POST discord.com")
        self.assertEqual(span.attributes["server.address"], "discord.com")
        self.assertEqual(span.attributes["http.response.status_code"], 204)
        flat = repr(dict(span.attributes)) + span.name
        self.assertNotIn("very-secret-token", flat)
        self.assertNotIn("webhooks", flat)

    def test_error_status_and_exception_type_only(self):
        self._open("https://canvas.skku.edu/api/v1/x", response=SimpleNamespace(status=404))
        with self.assertRaises(OSError):
            self._open("https://canvas.skku.edu/api/v1/x?access_token=abc", error=OSError("abc leaked"))
        first, second = self.exporter.get_finished_spans()
        self.assertEqual(first.attributes["error.type"], "404")
        self.assertEqual(second.attributes["error.type"], "OSError")
        self.assertEqual(second.events, ())  # exception message not recorded
        self.assertNotIn("abc", repr(dict(second.attributes)))


class OutboundDurationMetricTests(SimpleTestCase):
    def setUp(self):
        self.reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[self.reader])
        histogram = provider.get_meter("test").create_histogram("learningx.outbound.duration", unit="s")
        for target, value in (
            ("_outbound_duration", histogram),
            ("_tracer", TracerProvider().get_tracer("test")),
        ):
            patcher = mock.patch.object(network, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        resolve = mock.patch.object(network, "resolve_public_addresses", return_value=("203.0.113.5",))
        resolve.start()
        self.addCleanup(resolve.stop)

    def _points(self):
        data = self.reader.get_metrics_data()
        return [
            point
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            for point in metric.data.data_points
        ]

    def test_records_host_and_outcome_only(self):
        handler = network.PinnedHTTPSHandler()
        with mock.patch.object(handler, "do_open", return_value=SimpleNamespace(status=204)):
            handler.https_open(Request("https://discord.com/api/webhooks/1/secret-token", method="POST"))
        with mock.patch.object(handler, "do_open", return_value=SimpleNamespace(status=404)):
            handler.https_open(Request("https://canvas.skku.edu/api/v1/x?access_token=abc"))
        with mock.patch.object(handler, "do_open", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                handler.https_open(Request("https://canvas.skku.edu/api/v1/y"))
        attrs = sorted((dict(p.attributes)["server.address"], dict(p.attributes)["outcome"], p.count) for p in self._points())
        self.assertEqual(
            attrs,
            [("canvas.skku.edu", "error", 1), ("canvas.skku.edu", "http_error", 1), ("discord.com", "ok", 1)],
        )
        for point in self._points():
            self.assertEqual(set(point.attributes), {"server.address", "outcome"})
        self.assertNotIn("secret-token", repr([dict(p.attributes) for p in self._points()]))


class RequestSpanScrubTests(SimpleTestCase):
    def test_query_and_user_agent_are_overwritten(self):
        span = mock.Mock()
        span.is_recording.return_value = True
        span.attributes = {
            "http.target": "/accounts/google/login/callback/?code=secret&state=x",
            "user_agent.original": "Mozilla/5.0",
            "http.route": "accounts/google/login/callback/",
        }
        telemetry._scrub_request_span(span, None)
        written = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
        self.assertEqual(written, {"http.target": "[redacted]", "user_agent.original": "[redacted]"})

    def test_tracing_is_off_without_endpoint(self):
        with mock.patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": ""}):
            self.assertFalse(telemetry.configure_tracing_and_logs("test"))
