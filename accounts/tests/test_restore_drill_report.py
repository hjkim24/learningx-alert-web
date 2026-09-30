from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


class ReportRestoreDrillTests(SimpleTestCase):
    def test_ok_is_logged_at_info_with_counts_only(self):
        out = StringIO()
        with self.assertLogs("accounts.ops", level="INFO") as logs:
            call_command("report_restore_drill", "--status", "ok", "--tables", "24", "--rows", "334",
                         "--restore-seconds", "1", stdout=out)
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertEqual(logs.records[0].event, "restore_drill")
        self.assertIn("restore drill ok tables=24 rows=334 restore_seconds=1", out.getvalue())

    def test_failed_is_logged_as_error(self):
        with self.assertLogs("accounts.ops", level="ERROR") as logs:
            call_command("report_restore_drill", "--status", "failed", "--exit-code", "3", stdout=StringIO())
        self.assertIn("restore drill failed", logs.output[0])
        self.assertIn("exit_code=3", logs.output[0])
