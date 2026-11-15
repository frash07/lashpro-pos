from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Product, Service


@override_settings(
    ALLOWED_HOSTS=["testserver", "lashproke.co.ke", "pos.lashproke.co.ke"],
    POS_HOSTS=["pos.lashproke.co.ke"],
)
class StorefrontHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            sku="WEB-001",
            name="Lash Adhesive",
            cost_price=Decimal("300.00"),
            selling_price=Decimal("650.00"),
            on_hand=Decimal("12.000"),
            active=True,
        )
        cls.inactive_product = Product.objects.create(
            sku="WEB-002",
            name="Archived Adhesive",
            cost_price=Decimal("200.00"),
            selling_price=Decimal("450.00"),
            on_hand=Decimal("5.000"),
            active=False,
        )
        cls.service = Service.objects.create(
            name="Classic Lash Set",
            duration_minutes=90,
            price=Decimal("2500.00"),
            active=True,
        )

    def test_root_domain_renders_active_products_and_services(self):
        response = self.client.get(
            reverse("storefront:home"),
            HTTP_HOST="lashproke.co.ke",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lash Adhesive")
        self.assertContains(response, "Classic Lash Set")
        self.assertNotContains(response, "Archived Adhesive")
        self.assertEqual(response.context["product_count"], 1)
        self.assertEqual(response.context["service_count"], 1)

    def test_pos_hostname_root_redirects_to_staff_checkout(self):
        response = self.client.get(
            "/",
            HTTP_HOST="pos.lashproke.co.ke",
        )

        self.assertRedirects(
            response,
            reverse("sales:checkout"),
            fetch_redirect_response=False,
        )

    def test_product_filter_hides_services(self):
        response = self.client.get(
            "/",
            {"kind": "products", "q": "adhesive"},
            HTTP_HOST="lashproke.co.ke",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lash Adhesive")
        self.assertNotContains(response, "Classic Lash Set")
        self.assertEqual(response.context["product_count"], 1)
        self.assertEqual(response.context["service_count"], 0)
