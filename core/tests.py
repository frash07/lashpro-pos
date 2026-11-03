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

    def test_dashboard_contains_seven_categories_and_all_25_admin_destinations(self):
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
                "Artist Commissions",
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
        }

        self.assertEqual(len(destinations), 25)
        self.assertEqual(len(set(destinations)), 25)
        self.assertEqual(set(destinations), expected)
        self.assertContains(response, "Existing Django Admin Model Pages")
