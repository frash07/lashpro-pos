import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Product, Service
from customers.models import Customer
from sales.models import Sale
from .models import StorefrontOrder, StorefrontOrderLine, StorefrontProfile
from .services import create_storefront_order


User = get_user_model()


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


class StorefrontRegistrationTests(TestCase):
    def test_customer_can_register_without_receiving_staff_access(self):
        response = self.client.post(reverse("storefront:register"), {
            "full_name": "Amina Njeri",
            "email": "Amina@example.com",
            "phone": "+254 700 123 456",
            "password1": "Amina!StrongPassphrase943",
            "password2": "Amina!StrongPassphrase943",
        })

        self.assertRedirects(response, reverse("storefront:login"), fetch_redirect_response=False)
        user = User.objects.get(email="amina@example.com")
        profile = StorefrontProfile.objects.get(user=user)
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(profile.email, "amina@example.com")
        self.assertEqual(profile.customer.name, "Amina Njeri")
        self.assertEqual(profile.customer.phone, "+254 700 123 456")

    def test_customer_can_sign_in_with_email_and_view_orders(self):
        user = User.objects.create_user(
            username="web-existing-customer",
            email="client@example.com",
            password="Client!SecurePassphrase932",
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(name="Client One", phone="+254700000001")
        StorefrontProfile.objects.create(user=user, customer=customer, email="client@example.com")

        response = self.client.post(reverse("storefront:login"), {
            "email": "CLIENT@example.com",
            "password": "Client!SecurePassphrase932",
        })

        self.assertRedirects(response, reverse("storefront:account-orders"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_customer_account_cannot_access_staff_checkout(self):
        user = User.objects.create_user(
            username="web-no-pos-access",
            email="no-pos@example.com",
            password="Client!SecurePassphrase932",
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(name="No POS Access")
        StorefrontProfile.objects.create(user=user, customer=customer, email="no-pos@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("sales:checkout"))

        self.assertEqual(response.status_code, 403)


class StorefrontGuestCheckoutTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="GUEST-001",
            name="Lash Shampoo",
            cost_price=Decimal("200.00"),
            selling_price=Decimal("500.00"),
            on_hand=Decimal("5.000"),
            active=True,
        )

    def _set_cart(self, quantity=2):
        session = self.client.session
        session["storefront_cart"] = {str(self.product.pk): quantity}
        session.save()

    def test_guest_checkout_creates_order_request_without_pos_sale_or_payment(self):
        self._set_cart(quantity=2)
        key = uuid.uuid4()
        response = self.client.post(reverse("storefront:checkout"), {
            "idempotency_key": str(key),
            "full_name": "Guest Customer",
            "email": "guest@example.com",
            "phone": "+254 711 222 333",
            "notes": "Please call on arrival.",
        })

        self.assertEqual(response.status_code, 302)
        order = StorefrontOrder.objects.get()
        self.assertIn(order.access_token, response.url)
        self.assertEqual(order.status, StorefrontOrder.Status.PLACED)
        self.assertEqual(order.total_amount, Decimal("1000.00"))
        self.assertIsNone(order.account)
        self.assertIsNone(order.customer)
        line = order.lines.get()
        self.assertEqual(line.name_snapshot, "Lash Shampoo")
        self.assertEqual(line.sku_snapshot, "GUEST-001")
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_price, Decimal("500.00"))
        self.assertEqual(Sale.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("5.000"))

        detail = self.client.get(response.url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, order.reference)
        self.assertContains(detail, "not a payment confirmation")

    def test_guest_checkout_rejects_stock_that_is_no_longer_available(self):
        self._set_cart(quantity=6)
        response = self.client.post(reverse("storefront:checkout"), {
            "idempotency_key": str(uuid.uuid4()),
            "full_name": "Guest Customer",
            "email": "guest@example.com",
            "phone": "+254 711 222 333",
            "notes": "",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(StorefrontOrder.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("5.000"))

    def test_order_submission_is_idempotent(self):
        key = uuid.uuid4()
        kwargs = {
            "items": {str(self.product.pk): 1},
            "customer_name": "Repeat Guest",
            "customer_email": "repeat@example.com",
            "customer_phone": "+254 700 000 002",
            "idempotency_key": key,
        }
        first = create_storefront_order(**kwargs)
        second = create_storefront_order(**kwargs)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StorefrontOrder.objects.count(), 1)
        self.assertEqual(StorefrontOrderLine.objects.filter(order=first).count(), 1)

    def test_registered_checkout_links_to_existing_pos_customer(self):
        user = User.objects.create_user(
            username="web-linked-customer",
            email="linked@example.com",
            password="Client!SecurePassphrase932",
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(name="Linked Customer", phone="+254 733 000 001")
        StorefrontProfile.objects.create(user=user, customer=customer, email="linked@example.com")
        self.client.force_login(user)
        self._set_cart(quantity=1)

        response = self.client.post(reverse("storefront:checkout"), {
            "idempotency_key": str(uuid.uuid4()),
            "full_name": "Linked Customer",
            "email": "linked@example.com",
            "phone": "+254 733 000 001",
            "notes": "",
        })

        self.assertEqual(response.status_code, 302)
        order = StorefrontOrder.objects.get()
        self.assertEqual(order.account, user)
        self.assertEqual(order.customer, customer)

    def test_order_token_is_required_to_view_guest_order(self):
        order = create_storefront_order(
            items={str(self.product.pk): 1},
            customer_name="Private Guest",
            customer_email="private@example.com",
            customer_phone="+254700000003",
            idempotency_key=uuid.uuid4(),
        )
        response = self.client.get(reverse("storefront:order-detail", args=["invalid-token"]))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "private@example.com", status_code=404)
