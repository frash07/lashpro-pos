from django.test import TestCase
from django.urls import reverse

from accounts.models import User


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

    def test_dashboard_contains_nine_categories_and_all_28_destinations(self):
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
            "/admin-suite/integrations/",
            "/expenses/",
            "/admin/expenses/expense/",
        }

        self.assertEqual(len(destinations), 28)
        self.assertEqual(len(set(destinations)), 28)
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
