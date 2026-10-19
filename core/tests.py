import logging

from django.test import RequestFactory, SimpleTestCase

from core.log_filters import RedactSensitiveDataFilter
from core.views import health_check


class HealthCheckTests(SimpleTestCase):
    def test_returns_minimal_uncached_success_response(self):
        response = health_check(RequestFactory().get("/healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class SensitiveLogFilterTests(SimpleTestCase):
    def test_redacts_reset_and_receipt_tokens_and_sensitive_query_values(self):
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            __file__,
            1,
            "Request failed at /accounts/password-reset/user-id/reset-token/ "
            "and /sales/r/receipt-token/?reference=mpesa-secret",
            (),
            None,
        )

        RedactSensitiveDataFilter().filter(record)

        message = record.getMessage()
        for secret in ("reset-token", "receipt-token", "mpesa-secret"):
            self.assertNotIn(secret, message)
        self.assertIn("<redacted>", message)

    def test_redacts_database_urls_and_secret_assignments(self):
        record = logging.LogRecord(
            "app",
            logging.ERROR,
            __file__,
            1,
            "DATABASE_URL=postgresql://salon:private-password@db.example.test/lashpro "
            "DJANGO_SECRET_KEY=private-key",
            (),
            None,
        )

        RedactSensitiveDataFilter().filter(record)

        message = record.getMessage()
        for secret in ("private-password", "private-key", "db.example.test"):
            self.assertNotIn(secret, message)
