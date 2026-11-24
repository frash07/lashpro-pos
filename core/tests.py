import json
import logging
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from core.log_filters import RedactSensitiveDataFilter
from core.models import SharedDatabaseProbe
from core.views import health_check, home
from config.settings import _sentry_before_send


class HomeLandingTests(SimpleTestCase):
    def test_technician_role_lands_on_services_even_if_superuser(self):
        request = RequestFactory().get("/")
        request.user = type("TestUser", (), {
            "role": User.Role.TECHNICIAN,
            "is_superuser": True,
            "is_authenticated": True,
        })()

        response = home(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("sales:services"))


class HealthCheckTests(SimpleTestCase):
    def test_returns_minimal_uncached_success_response(self):
        response = health_check(RequestFactory().get("/healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class SensitiveLogFilterTests(SimpleTestCase):
    def test_redacts_reset_receipt_and_sensitive_query_values(self):
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


class SentryPrivacyTests(SimpleTestCase):
    def test_log_record_events_are_not_forwarded(self):
        event = {"message": "Sensitive checkout log"}

        self.assertIsNone(
            _sentry_before_send(event, {"log_record": object()})
        )

    def test_request_urls_and_payloads_are_removed(self):
        event = {
            "request": {
                "url": "https://lashpro-pos.fly.dev/sales/r/receipt-token/secret",
                "query_string": "customer=private",
                "data": {"mpesa_reference": "private"},
                "headers": {"Cookie": "session=private"},
            }
        }

        processed = _sentry_before_send(event, {})

        self.assertEqual(processed["request"], {})

    def test_sensitive_log_and_http_breadcrumbs_are_removed(self):
        event = {
            "breadcrumbs": {
                "values": [
                    {"category": "log", "message": "Sensitive customer detail"},
                    {"category": "http", "message": "GET /sales/r/receipt-token/secret"},
                    {"category": "view", "message": "Checkout view"},
                ]
            }
        }

        processed = _sentry_before_send(event, {})

        self.assertEqual(
            processed["breadcrumbs"]["values"],
            [{"category": "view", "message": "Checkout view"}],
        )

    def test_transaction_request_context_is_also_scrubbed(self):
        from config.settings import _sentry_before_send_transaction

        event = {
            "request": {
                "url": "https://lashpro-pos.fly.dev/accounts/password-reset/u/token",
            }
        }

        processed = _sentry_before_send_transaction(event, {})

        self.assertEqual(processed["request"], {})

class AdminSuiteAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager_staff = User.objects.create_user(
            username="admin-suite-manager-staff",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=True,
        )
        cls.manager_nonstaff = User.objects.create_user(
            username="admin-suite-manager-nonstaff",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=False,
        )
        cls.cashier_staff = User.objects.create_user(
            username="admin-suite-cashier-staff",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )

    def test_owner_manager_staff_can_open_admin_suite_dashboard(self):
        self.client.force_login(self.manager_staff)

        response = self.client.get(reverse("admin_suite"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Suite Dashboard")

    def test_staff_user_without_owner_or_manager_role_is_forbidden(self):
        self.client.force_login(self.cashier_staff)

        response = self.client.get(reverse("admin_suite"))

        self.assertEqual(response.status_code, 403)

    def test_manager_without_django_staff_status_cannot_open_admin_suite(self):
        self.client.force_login(self.manager_nonstaff)

        response = self.client.get(reverse("admin_suite"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_anonymous_user_is_redirected_to_admin_login(self):
        response = self.client.get(reverse("admin_suite"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_dashboard_contains_nine_categories_and_all_31_destinations(self):
        self.client.force_login(self.manager_staff)

        response = self.client.get(reverse("admin_suite"))

        self.assertEqual(response.status_code, 200)
        groups = response.context["groups"]
        self.assertEqual(
            [group["name"] for group in groups],
            [
                "People & Access",
                "Catalog",
                "Customers",
                "Sales",
                "Inventory",
                "Payments & Cash",
                "Expenses",
                "Artist Commissions",
                "Communications & Integrations",
            ],
        )
        destinations = [
            item["url"]
            for group in groups
            for item in group["items"]
        ]
        expected = {
            "/admin/accounts/user/",
            "/admin/audit/auditevent/",
            "/admin/auth/",
            "/admin/axes/accessattempt/",
            "/admin/axes/accessfailurelog/",
            "/admin/axes/accesslog/",
            "/admin/catalog/product/",
            "/admin/catalog/service/",
            "/admin/commissions/commissionledgerentry/",
            "/admin/commissions/commissionpayoutrecord/",
            "/admin/commissions/commissionpayoutrequest/",
            "/admin/customers/customer/",
            "/admin/inventory/inventorymovement/",
            "/admin/inventory/serviceconsumable/",
            "/admin/inventory/stockadjustmentrequest/",
            "/admin/payments/cashsessionmovement/",
            "/admin/payments/cashsession/",
            "/admin/payments/paymentreconciliation/",
            "/admin/payments/paymenttransaction/",
            "/admin/payments/payoutreconciliation/",
            "/admin/payments/refundpayout/",
            "/admin/payments/salepayment/",
            "/admin/sales/saleline/",
            "/admin/sales/salerefund/",
            "/admin/sales/sale/",
            "/admin/storefront/storefrontorder/",
            "/admin/storefront/whatsappinboundorder/",
            "/admin/storefront/whatsappcatalogsync/",
            "/admin-suite/integrations/",
            "/expenses/",
            "/admin/expenses/expense/",
        }

        self.assertEqual(len(destinations), 31)
        self.assertEqual(len(set(destinations)), 31)
        self.assertEqual(set(destinations), expected)
        self.assertContains(response, "Existing Django Admin Model Pages")


class ServiceWorkerCheckoutSafetyTests(TestCase):
    def test_failed_checkout_post_returns_status_unknown_guidance_not_offline_fallback(self):
        response = self.client.get(reverse("service_worker"))
        script = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn('request.method === "POST" && url.pathname === CHECKOUT_PATH', script)
        self.assertIn("Checkout status unknown", script)
        self.assertIn("Check Sales before retrying", script)
        self.assertIn('"Cache-Control": "no-store"', script)



class IntegrationSettingsAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="integration-settings-owner",
            password="test-password",
            role=User.Role.OWNER,
            is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="integration-settings-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )

    def test_owner_can_open_integration_settings_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("integrations-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "M-Pesa STK Push")
        self.assertContains(response, "KRA eTIMS")

    def test_cashier_cannot_open_integration_settings_page(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("integrations-settings"))
        self.assertEqual(response.status_code, 403)

    def test_credentials_are_encrypted_and_never_rendered_back(self):
        self.client.force_login(self.owner)
        secret = "AT-super-secret-test-api-key"
        response = self.client.post(reverse("integrations-settings"), {
            "sms_provider": "africastalking",
            "sms_username": "lashpro",
            "sms_api_key": secret,
            "sms_sandbox": "on",
            "mpesa_environment": "sandbox",
            "mpesa_transaction_type": "CustomerPayBillOnline",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        from core.models import IntegrationSettings
        record = IntegrationSettings.objects.get(pk=1)
        self.assertNotIn(secret, record.encrypted_config)
        self.assertEqual(record.get_config()["sms_api_key"], secret)
        self.assertNotContains(response, secret)



class SharedDatabaseProbeCommandTests(TestCase):
    def test_probe_can_be_created_verified_and_consumed(self):
        created_output = StringIO()
        call_command("shared_database_probe", "create", stdout=created_output)
        created = json.loads(created_output.getvalue())

        self.assertEqual(created["status"], "created")
        self.assertEqual(SharedDatabaseProbe.objects.count(), 1)
        self.assertTrue(created["database"]["connected_database"])

        verified_output = StringIO()
        call_command(
            "shared_database_probe",
            "verify",
            "--token",
            created["token"],
            stdout=verified_output,
        )
        verified = json.loads(verified_output.getvalue())

        self.assertEqual(verified["status"], "verified")
        self.assertTrue(verified["shared_record_visible"])
        self.assertTrue(verified["probe_consumed"])
        self.assertEqual(SharedDatabaseProbe.objects.count(), 0)

    def test_unknown_or_expired_probe_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "shared_database_probe",
                "verify",
                "--token",
                "00000000-0000-0000-0000-000000000001",
            )
