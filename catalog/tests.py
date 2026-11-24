from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.templatetags.static import static

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

    def test_product_workspace_is_standalone_and_preserves_controls(self):
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(response.status_code, 200)
        for marker in (
            "product-shell", 'id="product-grid"', 'id="product-actions"',
            'id="product-search"', 'id="product-menu-toggle"',
            'name="_selected_action"', static("sales/checkout-workspace.css"),
            static("css/tokens.css"), static("catalog/product-workspace.js"),
            "Low stock", "In stock",
        ):
            self.assertContains(response, marker)
        for marker in (
            'id="result_list"', 'id="changelist-filter"', 'id="nav-sidebar"',
            'id="header"', static("admin/css/base.css"), static("admin/css/changelists.css"),
            static("catalog/catalog-admin.css"),
        ):
            self.assertNotContains(response, marker)
        self.assertContains(response, reverse("admin:catalog_product_add"))
        self.assertContains(response, reverse("sales:checkout"))
        self.assertContains(response, reverse("admin:catalog_product_change", args=[self.product.pk]))
        self.assertContains(response, '>Classic Lash Adhesive</a>')
        self.assertEqual(response.context["workspace_counts"], {"active": 2, "low": 1})

    def test_product_popup_keeps_native_admin_changelist(self):
        response = self.client.get(
            reverse("admin:catalog_product_changelist"), {"_popup": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="result_list"')
        self.assertNotContains(response, 'id="product-grid"')

    def test_product_workspace_sort_and_page_links(self):
        url = reverse("admin:catalog_product_changelist")
        response = self.client.get(url)
        cl = response.context["cl"]
        price_index = cl.list_display.index("selling_price")
        response = self.client.get(url, {"o": "-" + str(price_index)})
        self.assertEqual(list(response.context["cl"].result_list), [self.low_stock_product, self.product])

        from unittest.mock import patch
        with patch.object(admin.site._registry[Product], "list_per_page", 1):
            response = self.client.get(url, {"p": 2})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Volume Lash Tray")
            self.assertNotContains(response, "Classic Lash Adhesive")
            self.assertTrue(response.context["workspace_previous"])

    def test_product_workspace_bulk_delete_requires_confirmation(self):
        response = self.client.post(reverse("admin:catalog_product_changelist"), {
            "action": "delete_selected",
            "index": "0",
            "select_across": "0",
            "_selected_action": [str(self.product.pk)],
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/delete_selected_confirmation.html")
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_product_sort_and_combined_search_filter_work(self):
        response = self.client.get(
            reverse("admin:catalog_product_changelist"),
            {"q": "Volume", "stock_level": "low", "o": "4"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Volume Lash Tray")
        self.assertNotContains(response, "Classic Lash Adhesive")

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
        product_admin = admin.site._registry[Product]
        self.assertIn("on_hand", product_admin.get_readonly_fields(None, self.product))
        self.assertIn("sku", product_admin.get_readonly_fields(None, self.product))

    def test_existing_meta_retailer_id_can_be_mapped_before_publication(self):
        product_admin = admin.site._registry[Product]
        readonly = product_admin.get_readonly_fields(None, self.product)
        self.assertNotIn("whatsapp_retailer_id", readonly)

        self.product.whatsapp_retailer_id = "META-CONTENT-001"
        self.product.save(update_fields=("whatsapp_retailer_id",))
        self.assertEqual(self.product.whatsapp_retailer_id, "META-CONTENT-001")

    def test_meta_retailer_id_cannot_collide_with_another_sku(self):
        self.low_stock_product.whatsapp_retailer_id = self.product.sku
        with self.assertRaises(ValidationError):
            self.low_stock_product.save(update_fields=("whatsapp_retailer_id",))

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
