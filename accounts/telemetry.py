"""OpenTelemetry metrics for the scheduler.

Instruments come from the global meter, which is a no-op until
``configure_metrics()`` installs a real provider, so importing and recording
is always safe (tests, local dev, a host with no collector).

Attributes are low-cardinality on purpose: status, kind and error code only,
never a user, course or run id, so the series count stays small and nothing
personal leaves the host.
"""

import os

from opentelemetry import metrics

_meter = metrics.get_meter("learningx_alert.scheduler")

heartbeat = _meter.create_counter(
    "learningx.scheduler.scans",
    description="Scheduler loop iterations; flat means the scheduler is stuck or down",
)
runs = _meter.create_counter(
    "learningx.runs",
    description="Scheduled runs finished, by final status",
)
run_delay = _meter.create_histogram(
    "learningx.run.start_delay",
    unit="s",
    description="Seconds between an alarm's scheduled time and the run starting",
)
deliveries = _meter.create_counter(
    "learningx.deliveries",
    description="Delivery parts finished, by destination kind and status",
)
course_results = _meter.create_counter(
    "learningx.course_results",
    description="Per-course collection outcomes, by status and error code",
)
# Wall-clock view of one scan. ScheduledRun.started_at is the scan's `now` for
# every run in the batch, so start_delay above cannot show the queueing that
# serial processing adds; these can.
run_actual_delay = _meter.create_histogram(
    "learningx.run.actual_start_delay",
    unit="s",
    description="Seconds from an alarm's scheduled time to its run really starting (queue wait included)",
)
run_duration = _meter.create_histogram(
    "learningx.run.duration",
    unit="s",
    description="Wall-clock seconds one scheduled run took",
)
scan_duration = _meter.create_histogram(
    "learningx.scan.duration",
    unit="s",
    description="Wall-clock seconds one scan spent running its due runs",
)
scan_batch = _meter.create_histogram(
    "learningx.scan.batch_size",
    description="Due runs claimed by one scan",
)
# Per-school capacity, reported by the scheduler each scan. The ``school``
# code is the only attribute (a handful of values).
school_connections = _meter.create_gauge(
    "learningx.school.connections",
    description="Canvas connections per school",
)
school_capacity = _meter.create_gauge(
    "learningx.school.capacity",
    description="SCHOOL_MAX_USERS for each enabled school (0 = no cap)",
)

_configured = False
_tracing_configured = False


def _resource(service_name):
    from opentelemetry.sdk.resources import Resource

    return Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "learningx-alert",
            "deployment.environment": os.environ.get("DEPLOYMENT_ENVIRONMENT", "production"),
        }
    )


def configure_metrics(service_name):
    """Install an OTLP/HTTP exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    Returns True when metrics will be exported. The export interval defaults
    to 60s and can be tuned with OTEL_METRIC_EXPORT_INTERVAL (ms).
    """
    global _configured
    if _configured or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return _configured

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    metrics.set_meter_provider(
        MeterProvider(resource=_resource(service_name), metric_readers=[reader])
    )
    _configured = True
    return True


def configure_tracing_and_logs(service_name, *, sample_ratio=1.0):
    """Traces (sampled) and log shipping over OTLP, plus Django/PyMySQL spans.

    Call once per process *after* any fork (the batch exporters start a
    thread). Logs reuse the stdout pipeline's redacting filter, so nothing is
    exported that would not already be printed.
    """
    global _tracing_configured
    if _tracing_configured or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return _tracing_configured

    import logging

    from opentelemetry import trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = _resource(service_name)
    tracer_provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(sample_ratio))
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(_safe_logging_handler(logger_provider))

    _instrument_libraries()
    _tracing_configured = True
    return True


def _safe_logging_handler(logger_provider):
    """OTel LoggingHandler that exports a scrubbed *copy* of each record.

    Only standard LogRecord fields plus our allowlisted ``extra`` keys are
    exported: Django attaches the whole ``request`` (its repr holds the query
    string). Exceptions are reduced to type + frames, never the message.
    """
    import copy
    import logging
    import traceback

    from opentelemetry.sdk._logs import LoggingHandler

    from config.logging import _EXTRA_FIELDS, redact

    standard = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
        "message",
        "asctime",
    }

    class SafeLoggingHandler(LoggingHandler):
        def emit(self, record):
            if record.name.startswith("opentelemetry"):
                return  # exporter errors must not feed back into the exporter
            safe = copy.copy(record)
            for key in list(vars(safe)):
                if key not in standard and key not in _EXTRA_FIELDS:
                    delattr(safe, key)
            safe.msg = redact(record.getMessage())
            safe.args = ()
            if record.exc_info:
                exc_type, _exc, tb = record.exc_info
                frames = "".join(traceback.format_list(traceback.extract_tb(tb)))
                safe.exception_type = exc_type.__name__
                safe.stack = redact(frames)
            safe.exc_info = None
            safe.exc_text = None
            super().emit(safe)

    return SafeLoggingHandler(level=logging.INFO, logger_provider=logger_provider)


def _instrument_libraries():
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.pymysql import PyMySQLInstrumentor

    DjangoInstrumentor().instrument(
        excluded_urls="healthz,sw.js,manifest.webmanifest,static/.*",
        # Never record query strings, headers or bodies.
        request_hook=_scrub_request_span,
    )
    PyMySQLInstrumentor().instrument(enable_commenter=False)


_SCRUBBED_ATTRIBUTES = ("http.target", "url.query", "http.url", "url.full", "http.user_agent", "user_agent.original")


def _scrub_request_span(span, _request):
    if not span or not span.is_recording():
        return
    # Attributes are set before the hook runs; overwrite the ones that can
    # carry a query string (e.g. OAuth "code"/"state") or a fingerprintable UA.
    for key in _SCRUBBED_ATTRIBUTES:
        if key in getattr(span, "attributes", {}):
            span.set_attribute(key, "[redacted]")


def shutdown():
    from opentelemetry import _logs, trace

    for provider in (
        metrics.get_meter_provider(),
        trace.get_tracer_provider(),
        _logs.get_logger_provider(),
    ):
        if hasattr(provider, "shutdown"):
            provider.shutdown()
