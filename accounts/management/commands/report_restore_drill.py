"""Report a restore-drill result to the log pipeline (and so to Grafana).

deploy/restore-drill-report.sh runs this inside the web container after the
monthly drill. It only logs counts and a status: no table contents, no paths.
"""

import logging

from django.core.management.base import BaseCommand

from accounts import telemetry

logger = logging.getLogger("accounts.ops")


class Command(BaseCommand):
    help = "Log the outcome of deploy/restore-drill.sh (counts only)."

    def add_arguments(self, parser):
        parser.add_argument("--status", choices=("ok", "failed"), required=True)
        parser.add_argument("--tables", type=int, default=0)
        parser.add_argument("--rows", type=int, default=0)
        parser.add_argument("--restore-seconds", type=int, default=0)
        parser.add_argument("--differences", type=int, default=0)
        parser.add_argument("--exit-code", type=int, default=0)

    def handle(self, *args, **options):
        telemetry.configure_tracing_and_logs("learningx-alert-ops")
        try:
            message = (
                f"restore drill {options['status']} tables={options['tables']} "
                f"rows={options['rows']} restore_seconds={options['restore_seconds']} "
                f"differences={options['differences']} exit_code={options['exit_code']}"
            )
            level = logging.INFO if options["status"] == "ok" else logging.ERROR
            logger.log(level, message, extra={"event": "restore_drill", "status": options["status"]})
            self.stdout.write(message)
        finally:
            # Flush the batch log exporter before the process exits.
            telemetry.shutdown()
