import fcntl
import hashlib
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.scheduling import reconcile_interrupted_runs, run_due_rules


@contextmanager
def scheduler_lock():
    database_name = str(settings.DATABASES["default"]["NAME"]).encode()
    database_key = hashlib.sha256(database_name).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"learningx-alert-{database_key}.lock"
    # ponytail: host-local lock matches the single-host pilot; use a DB lease for multiple hosts.
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
        try:
            with scheduler_lock():
                reconcile_interrupted_runs(timezone.now())
                while True:
                    scan_started_at = time.time()
                    runs = run_due_rules(timezone.now())
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
