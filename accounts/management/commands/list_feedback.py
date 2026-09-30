"""Read feedback on the server, without opening any web page.

    python manage.py list_feedback            # new feedback, newest first
    python manage.py list_feedback --all      # including handled ones
    python manage.py list_feedback --done 12  # mark #12 handled
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Feedback


class Command(BaseCommand):
    help = "List feedback, or mark one as handled"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Include handled feedback")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--done", type=int, metavar="ID", help="Mark this feedback handled")

    def handle(self, *args, **options):
        if options["done"] is not None:
            updated = Feedback.objects.filter(pk=options["done"]).update(status=Feedback.Status.DONE)
            if not updated:
                raise CommandError(f"no feedback #{options['done']}")
            self.stdout.write(f"#{options['done']} marked done")
            return
        entries = Feedback.objects.select_related("user")
        if not options["all"]:
            entries = entries.filter(status=Feedback.Status.NEW)
        entries = list(entries[: max(1, options["limit"])])
        if not entries:
            self.stdout.write("no feedback")
            return
        for entry in entries:
            context = " · ".join(
                str(value)
                for value in (
                    entry.page_path,
                    entry.client,
                    "홈 화면 앱" if entry.standalone else "",
                    entry.app_revision[:7],
                    f"run {entry.latest_run_id}" if entry.latest_run_id else "",
                )
                if value
            )
            self.stdout.write(
                f"#{entry.pk} [{entry.get_category_display()}] {entry.get_status_display()} "
                f"{entry.created_at:%Y-%m-%d %H:%M} {entry.user.email or entry.user.username}"
            )
            if context:
                self.stdout.write(f"  {context}")
            for line in entry.message.splitlines() or [""]:
                self.stdout.write(f"  | {line}")
