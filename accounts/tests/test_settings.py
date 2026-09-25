import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ProductionSettingsTests(SimpleTestCase):
    def test_production_rejects_missing_secrets(self):
        env = os.environ.copy()
        env["DJANGO_DEBUG"] = "0"
        for name in (
            "DJANGO_SECRET_KEY",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "CREDENTIAL_ENCRYPTION_KEYS",
        ):
            env.pop(name, None)

        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("Missing required production configuration", output)
        self.assertIn("DJANGO_SECRET_KEY", output)
        self.assertIn("GOOGLE_CLIENT_ID", output)
        self.assertIn("GOOGLE_CLIENT_SECRET", output)
        self.assertIn("CREDENTIAL_ENCRYPTION_KEYS", output)

    def test_production_enables_secure_session_and_csrf_cookies(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "0",
                "DJANGO_SECRET_KEY": "production-test-secret",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-client-secret",
                "CREDENTIAL_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from config import settings; "
                    "print(settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE)"
                ),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True")
