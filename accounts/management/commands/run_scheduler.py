import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.scheduling import reconcile_interrupted_runs, run_due_rules


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
            reconcile_interrupted_runs(timezone.now())
            while True:
                runs = run_due_rules(timezone.now())
                self.stdout.write(f"scheduled_runs={len(runs)}")
                if options["once"]:
                    return
                seconds_to_next_minute = min(60, 60 - (time.time() % 60))
                time.sleep(seconds_to_next_minute)
        except KeyboardInterrupt:
            self.stdout.write("scheduler stopped")
