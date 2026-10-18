from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Product


User = get_user_model()


class AdminInventoryDashboardTests(TestCase):
    def test_inventory_links_and_low_stock_alert_are_visible_to_admin(self):
        administrator = User.objects.create_superuser(
            username="admin-dashboard-test",
            email="admin-dashboard@example.com",
            password="Strong-Test-Password!485",
        )
        Product.objects.create(
            sku="ADMIN-LOW-001",
            name="Admin Dashboard Low Stock Test",
            cost_price=Decimal("5.00"),
            selling_price=Decimal("10.00"),
            on_hand=Decimal("1.000"),
            reorder_level=Decimal("3.000"),
        )
        self.client.force_login(administrator)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Products and stock levels")
        self.assertContains(response, "Inventory movement history")
        self.assertContains(response, "Low-stock alert")
        self.assertContains(response, "Admin Dashboard Low Stock Test")
        self.assertContains(response, reverse("admin:catalog_product_changelist"))
