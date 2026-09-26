import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ProductionSettingsTests(SimpleTestCase):
    def production_env(self):
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
        return env

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

    def test_production_rejects_malformed_fernet_key_without_echoing_it(self):
        malformed_key = "malformed-key-must-not-appear"
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "0",
                "DJANGO_SECRET_KEY": "production-test-secret",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-client-secret",
                "CREDENTIAL_ENCRYPTION_KEYS": malformed_key,
            }
        )

        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn(
            "CREDENTIAL_ENCRYPTION_KEYS must contain valid Fernet keys",
            output,
        )
        self.assertNotIn(malformed_key, output)

    def test_file_secrets_override_environment(self):
        env = self.production_env()
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_dir = Path(temp_dir)
            django_secret = "file-django-secret"
            google_secret = "file-google-secret"
            encryption_key = Fernet.generate_key().decode()
            secret_files = {
                "DJANGO_SECRET_KEY_FILE": ("django", django_secret),
                "GOOGLE_CLIENT_SECRET_FILE": ("google", google_secret),
                "CREDENTIAL_ENCRYPTION_KEYS_FILE": ("fernet", encryption_key),
            }
            for env_name, (file_name, value) in secret_files.items():
                path = secret_dir / file_name
                path.write_text(value + "\n", encoding="utf-8")
                env[env_name] = str(path)
            env.update(
                {
                    "EXPECTED_DJANGO_SECRET": django_secret,
                    "EXPECTED_GOOGLE_SECRET": google_secret,
                    "EXPECTED_ENCRYPTION_KEY": encryption_key,
                }
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os; from config import settings; "
                        "print(settings.SECRET_KEY == os.environ['EXPECTED_DJANGO_SECRET'], "
                        "settings.GOOGLE_CLIENT_SECRET == os.environ['EXPECTED_GOOGLE_SECRET'], "
                        "settings.CREDENTIAL_ENCRYPTION_KEYS == "
                        "[os.environ['EXPECTED_ENCRYPTION_KEY']])"
                    ),
                ],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True True")

    def test_empty_file_secret_fails_closed_without_echo(self):
        env = self.production_env()
        fallback_secret = "fallback-must-not-appear"
        env["DJANGO_SECRET_KEY"] = fallback_secret
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty-secret-path-must-not-appear"
            path.write_text("\n", encoding="utf-8")
            env["DJANGO_SECRET_KEY_FILE"] = str(path)

            result = subprocess.run(
                [sys.executable, "manage.py", "check"],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("DJANGO_SECRET_KEY_FILE", output)
        self.assertNotIn(str(path), output)
        self.assertNotIn(fallback_secret, output)

    def test_unreadable_file_secret_fails_closed_without_echo(self):
        env = self.production_env()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing-secret-path-must-not-appear"
            env["DJANGO_SECRET_KEY_FILE"] = str(path)

            result = subprocess.run(
                [sys.executable, "manage.py", "check"],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("DJANGO_SECRET_KEY_FILE", output)
        self.assertNotIn(str(path), output)

    def test_production_configures_expected_proxy_origin_and_host(self):
        env = self.production_env()
        env.update(
            {
                "DJANGO_ALLOWED_HOSTS": "alert.sobok-app.com",
                "CSRF_TRUSTED_ORIGINS": "https://alert.sobok-app.com",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from config import settings; "
                    "print(settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS, "
                    "settings.SECURE_PROXY_SSL_HEADER)"
                ),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "['alert.sobok-app.com'] ['https://alert.sobok-app.com'] "
            "('HTTP_X_FORWARDED_PROTO', 'https')",
        )
