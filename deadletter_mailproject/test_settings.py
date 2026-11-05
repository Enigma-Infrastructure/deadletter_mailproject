"""Subprocess checks prevent settings imports leaking between environments."""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


class EnvironmentSettingsTests(SimpleTestCase):
    def inspect_settings(self, module, **overrides):
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("DJANGO_")
        }
        environment.update(overrides)
        environment["DJANGO_SETTINGS_MODULE"] = module
        script = (
            "import json; from django.conf import settings as s; "
            "print(json.dumps({'debug': s.DEBUG, 'hosts': s.ALLOWED_HOSTS, "
            "'session_secure': s.SESSION_COOKIE_SECURE, "
            "'csrf_secure': s.CSRF_COOKIE_SECURE, "
            "'redirect': s.SECURE_SSL_REDIRECT, "
            "'proxy': s.SECURE_PROXY_SSL_HEADER, "
            "'hsts_seconds': getattr(s, 'SECURE_HSTS_SECONDS', 0), "
            "'database': str(s.DATABASES['default']['NAME'])}))"
        )
        return subprocess.run(
            [sys.executable, "-c", script], env=environment,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=30,
        )

    def production(self, **overrides):
        environment = {
            "DJANGO_SECRET_KEY": "test-only-key-not-for-deployment-0123456789-abcdefghij",
            "DJANGO_ALLOWED_HOSTS": "demo.example.com",
        }
        environment.update(overrides)
        return self.inspect_settings(
            "deadletter_mailproject.settings_production", **environment
        )

    def test_local_defaults_are_preserved(self):
        result = self.inspect_settings("deadletter_mailproject.settings")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertTrue(values["debug"])
        self.assertEqual(values["hosts"], ["localhost", "127.0.0.1"])
        self.assertFalse(values["session_secure"])
        self.assertFalse(values["redirect"])

    def test_production_forces_https_and_disables_debug(self):
        result = self.production(DJANGO_DEBUG="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertFalse(values["debug"])
        self.assertTrue(values["session_secure"])
        self.assertTrue(values["csrf_secure"])
        self.assertTrue(values["redirect"])
        self.assertIsNone(values["proxy"])
        self.assertEqual(values["hsts_seconds"], 31536000)

    def test_production_rejects_missing_or_weak_secret(self):
        for secret in ("", "short", "x" * 60):
            with self.subTest(secret_length=len(secret)):
                result = self.production(DJANGO_SECRET_KEY=secret)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Production requires DJANGO_SECRET_KEY", result.stderr)

    def test_production_rejects_implicit_hosts(self):
        for hosts in ("", "*", ".example.com", "https://demo.example.com"):
            with self.subTest(hosts=hosts):
                result = self.production(DJANGO_ALLOWED_HOSTS=hosts)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_explicit_proxy_trust(self):
        result = self.production(DJANGO_TRUST_PROXY_HTTPS="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["proxy"],
            ["HTTP_X_FORWARDED_PROTO", "https"],
        )

    def test_invalid_proxy_boolean_is_rejected(self):
        result = self.production(DJANGO_TRUST_PROXY_HTTPS="maybe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_TRUST_PROXY_HTTPS", result.stderr)

    def test_relative_database_path_is_rejected(self):
        result = self.production(DJANGO_DB_PATH="relative.sqlite3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_DB_PATH must be an absolute path", result.stderr)
