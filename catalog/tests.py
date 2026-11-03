from decimal import Decimal

from django.contrib import admin
from django.test import TestCase
from django.urls import reverse

from catalog.admin import ProductAdmin
from catalog.models import Product, Service
from accounts.models import User


class CatalogAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username="catalog-admin",
            email="catalog-admin@example.test",
            password="test-password",
        )
        cls.product = Product.objects.create(
            sku="LASH-001",
            name="Classic Lash Adhesive",
            cost_price=Decimal("500.00"),
            selling_price=Decimal("850.00"),
            on_hand=Decimal("12.000"),
            reorder_level=Decimal("5.000"),
        )
        cls.low_stock_product = Product.objects.create(
            sku="LASH-002",
            name="Volume Lash Tray",
            cost_price=Decimal("700.00"),
            selling_price=Decimal("1200.00"),
            on_hand=Decimal("2.000"),
            reorder_level=Decimal("5.000"),
        )
        cls.service = Service.objects.create(
            name="Classic Full Set",
            duration_minutes=90,
            price=Decimal("3500.00"),
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_product_admin_list_and_search_work(self):
        url = reverse("admin:catalog_product_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.sku)

        response = self.client.get(url, {"q": "Classic Lash Adhesive"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classic Lash Adhesive")
        self.assertNotContains(response, "Volume Lash Tray")

    def test_product_low_stock_filter_works(self):
        url = reverse("admin:catalog_product_changelist")
        response = self.client.get(url, {"stock_level": "low"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Volume Lash Tray")
        self.assertNotContains(response, "Classic Lash Adhesive")

    def test_existing_product_stock_and_sku_are_read_only(self):
        url = reverse("admin:catalog_product_change", args=[self.product.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        readonly = response.context["adminform"].form.fields
        self.assertNotIn("on_hand", readonly)
        self.assertNotIn("sku", readonly)
        self.assertIn("on_hand", response.context["adminform"].form._meta.fields or ())

    def test_service_admin_list_and_search_work(self):
        url = reverse("admin:catalog_service_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.service.name)

        response = self.client.get(url, {"q": self.service.name})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.service.name)

    def test_non_staff_user_cannot_open_catalog_admin(self):
        cashier = User.objects.create_user(
            username="catalog-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=False,
        )
        self.client.force_login(cashier)
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
