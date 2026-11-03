from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer


class CustomerAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username="customer-admin",
            email="customer-admin@example.test",
            password="test-password",
        )
        cls.customer = Customer.objects.create(
            name="Amina Client",
            phone="+254700000001",
            notes="Prefers evening appointments.",
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_customer_admin_list_displays_existing_records(self):
        response = self.client.get(reverse("admin:customers_customer_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.name)
        self.assertContains(response, "Customer directory")
        self.assertContains(response, "Purchase history")

    def test_customer_directory_summary_counts_filtered_records(self):
        Customer.objects.create(name="Walk-in Client")
        response = self.client.get(reverse("admin:customers_customer_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["customer_summary"],
            {
                "customer_count": 2,
                "with_phone": 1,
                "with_sales": 0,
                "with_notes": 1,
            },
        )

    def test_customer_admin_add_page_is_available(self):
        response = self.client.get(reverse("admin:customers_customer_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "name")
        self.assertContains(response, "phone")

    def test_customer_admin_can_create_a_customer(self):
        response = self.client.post(
            reverse("admin:customers_customer_add"),
            {
                "name": "New Customer",
                "phone": "+254700000002",
                "notes": "New customer record.",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(name="New Customer").exists())

    def test_customer_admin_change_page_preserves_customer_details(self):
        response = self.client.get(
            reverse("admin:customers_customer_change", args=[self.customer.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.phone)

    def test_non_staff_user_cannot_open_customer_admin(self):
        cashier = User.objects.create_user(
            username="customer-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=False,
        )
        self.client.force_login(cashier)
        response = self.client.get(reverse("admin:customers_customer_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
    