import json
import subprocess
import sys

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.tests import test_settings as base_settings

PROJECT_ROOT = base_settings.PROJECT_ROOT


class ContentSecurityPolicyTests(TestCase):
    def test_pages_carry_report_only_policy(self):
        response = Client().get(reverse("account_login"))

        policy = response["Content-Security-Policy-Report-Only"]
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("report-uri /csp-report/", policy)
        # Report-only: nothing is enforced yet.
        self.assertNotIn("Content-Security-Policy", response.headers.keys() - {
            "Content-Security-Policy-Report-Only"
        })

    @override_settings(CSP_REPORT_ONLY=False)
    def test_policy_can_be_switched_off(self):
        response = Client().get(reverse("account_login"))

        self.assertNotIn("Content-Security-Policy-Report-Only", response)

    def test_report_is_logged_without_query_or_full_url(self):
        report = {
            "csp-report": {
                "document-uri": "https://alert.sobok-app.com/connection/?code=secret-code",
                "effective-directive": "script-src-elem",
                "blocked-uri": "https://evil.example/path/token-in-path.js?x=1",
            }
        }
        with self.assertLogs("config.csp", level="WARNING") as logs:
            response = Client().post(
                reverse("csp_report"),
                data=json.dumps(report),
                content_type="application/csp-report",
            )

        self.assertEqual(response.status_code, 204)
        line = logs.output[0]
        self.assertIn("directive=script-src-elem", line)
        self.assertIn("blocked=https://evil.example", line)
        self.assertIn("page=/connection/", line)
        self.assertNotIn("secret-code", line)
        self.assertNotIn("token-in-path", line)

    def test_report_rejects_oversized_or_malformed_bodies(self):
        client = Client()
        self.assertEqual(
            client.post(reverse("csp_report"), data="x" * 9000, content_type="application/json").status_code,
            413,
        )
        self.assertEqual(
            client.post(reverse("csp_report"), data="not json", content_type="application/json").status_code,
            400,
        )
        self.assertEqual(client.get(reverse("csp_report")).status_code, 405)


class ProductionHeaderSettingsTests(SimpleTestCase):
    def test_production_sets_short_hsts_and_hashed_static_storage(self):
        env = base_settings.ProductionSettingsTests().production_env()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; "
                "from django.conf import settings; "
                "print(settings.SECURE_HSTS_SECONDS, settings.SECURE_HSTS_INCLUDE_SUBDOMAINS, "
                "settings.SECURE_HSTS_PRELOAD, settings.STORAGES['staticfiles']['BACKEND'].rsplit('.', 1)[-1])",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            result.stdout.split(), ["3600", "False", "False", "ManifestStaticFilesStorage"]
        )

    def test_caddy_caches_only_hashed_static_files(self):
        caddyfile = (PROJECT_ROOT / "deploy" / "Caddyfile").read_text()

        self.assertIn('Strict-Transport-Security "max-age=3600"', caddyfile)
        self.assertIn(r"path_regexp \.[0-9a-f]{12}\.[A-Za-z0-9]+$", caddyfile)
        self.assertIn("immutable", caddyfile)
        self.assertNotIn("includeSubDomains", caddyfile)
