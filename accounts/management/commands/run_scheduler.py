import fcntl
import hashlib
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts import telemetry
from accounts.scheduling import CATCH_UP_MINUTES, reconcile_interrupted_runs, run_due_rules
from accounts.schools import record_school_gauges

logger = logging.getLogger(__name__)


@contextmanager
def scheduler_lock():
    database = settings.DATABASES["default"]
    database_name = str(database["NAME"])
    if database["ENGINE"] != "django.db.backends.sqlite3":
        # Server databases have no file to sit next to; keep the lock on the
        # shared data volume (DATABASE_PATH's directory) so every container on
        # this host contends for the same file.
        database_key = hashlib.sha256(
            f"{database.get('HOST', '')}/{database_name}".encode()
        ).hexdigest()[:16]
        data_path = os.environ.get("DATABASE_PATH", "")
        lock_dir = Path(data_path).parent if data_path else Path(tempfile.gettempdir())
        if not lock_dir.is_dir():
            lock_dir = Path(tempfile.gettempdir())
        lock_path = lock_dir / f"learningx-alert-{database_key}.scheduler.lock"
    elif database_name.startswith("file:") and "mode=memory" in database_name:
        database_key = hashlib.sha256(database_name.encode()).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"learningx-alert-{database_key}.lock"
    else:
        database_path = Path(database_name)
        lock_path = database_path.with_name(f"{database_path.name}.scheduler.lock")
    # ponytail: shared-volume lock covers one host; use a DB lease for multiple hosts.
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CommandError("scheduler already running") from None
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class Command(BaseCommand):
    help = "Run the LearningX alert scheduler"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Reconcile and scan once, then exit",
        )

    def handle(self, *args, **options):
        exporting = telemetry.configure_metrics("learningx-alert-scheduler")
        telemetry.configure_tracing_and_logs("learningx-alert-scheduler", sample_ratio=1.0)
        # stdout, not logging: the worker tests pin time.time(), which every
        # LogRecord reads.
        self.stdout.write(f"scheduler starting metrics={'on' if exporting else 'off'}")
        try:
            with scheduler_lock():
                started = timezone.now()
                reconcile_interrupted_runs(started)
                # First scan looks back CATCH_UP_MINUTES so a restart at an
                # alarm minute (deploy, crash) still sends it; later scans
                # cover every minute since the previous scan.
                since = started - timedelta(minutes=CATCH_UP_MINUTES)
                while True:
                    scan_started_at = time.time()
                    scan_now = timezone.now()
                    try:
                        runs = run_due_rules(scan_now, since=since)
                    except Exception:
                        # Counted but still raised: the container restarts, and
                        # the flat heartbeat plus this line say why.
                        telemetry.heartbeat.add(1, {"outcome": "error"})
                        logger.exception("scan failed", extra={"event": "scan_failed"})
                        raise
                    since = scan_now
                    telemetry.heartbeat.add(1, {"outcome": "ok"})
                    try:
                        record_school_gauges()
                    except Exception:  # telemetry must never stop the loop
                        logger.exception("school gauges failed", extra={"event": "telemetry_error"})
                    self.stdout.write(f"scheduled_runs={len(runs)}")
                    if options["once"]:
                        return
                    scan_finished_at = time.time()
                    if int(scan_finished_at // 60) != int(scan_started_at // 60):
                        continue
                    seconds_to_next_minute = min(60, 60 - (scan_finished_at % 60))
                    time.sleep(seconds_to_next_minute)
        except KeyboardInterrupt:
            self.stdout.write("scheduler stopped")
        finally:
            telemetry.shutdown()
