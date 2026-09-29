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

_configured = False


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
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "learningx-alert",
            "deployment.environment": os.environ.get("DEPLOYMENT_ENVIRONMENT", "production"),
        }
    )
    reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    _configured = True
    return True


def shutdown():
    provider = metrics.get_meter_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
