import os

import django
from django.core.handlers.wsgi import WSGIHandler


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Same as get_wsgi_application(), split so telemetry lands in the right order:
# setup() applies LOGGING (which would drop a handler added earlier), then the
# instrumentor inserts its middleware, then the handler loads the middleware.
# gunicorn imports this inside each worker (no --preload), so the exporter
# threads start after the fork. Web traffic is sampled at 20% by default.
django.setup(set_prefix=False)
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
    from accounts import telemetry

    # Metrics first so the Django instrumentor's request-duration histogram
    # and the outbound-call histogram bind to the real provider.
    telemetry.configure_metrics("learningx-alert-web")
    telemetry.configure_tracing_and_logs(
        "learningx-alert-web",
        sample_ratio=float(os.environ.get("OTEL_TRACES_SAMPLE_RATIO", "0.2")),
    )

application = WSGIHandler()
