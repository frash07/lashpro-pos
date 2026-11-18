from datetime import timedelta
from decimal import Decimal
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from catalog.models import Product
from inventory.services import available_stock_for_product
from storefront.models import StorefrontOrder, StorefrontStockReservation
from storefront.services import create_storefront_order, expire_due_storefront_orders, transition_storefront_order


User = get_user_model()


class StorefrontReservationExpiryTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="expiry-owner", password="Owner!SecurePassphrase932",
            role=User.Role.OWNER, is_staff=True,
        )
        self.product = Product.objects.create(
            sku="EXPIRY-001", name="Expiry Lash Glue",
            cost_price=Decimal("100.00"), selling_price=Decimal("300.00"),
            on_hand=Decimal("5.000"), active=True,
        )

    def _create_order(self, quantity=2):
        return create_storefront_order(
            items={str(self.product.pk): quantity},
            customer_name="Expiry Test Customer",
            customer_email="expiry@example.com",
            customer_phone="+254700000001",
            idempotency_key=uuid.uuid4(),
        )

    def test_expired_placed_order_stops_reserving_stock_before_cleanup(self):
        order = self._create_order()
        order.expires_at = timezone.now() - timedelta(seconds=1)
        order.save(update_fields=("expires_at",))

        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))
        reservation = StorefrontStockReservation.objects.get(order_line=order.lines.get())
        self.assertEqual(reservation.status, StorefrontStockReservation.Status.ACTIVE)

        self.assertEqual(expire_due_storefront_orders(), 1)
        order.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(order.status, StorefrontOrder.Status.EXPIRED)
        self.assertIsNotNone(order.expired_at)
        self.assertEqual(reservation.status, StorefrontStockReservation.Status.RELEASED)
        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))

    def test_confirmed_order_does_not_expire_with_original_public_hold_deadline(self):
        order = self._create_order()
        transition_storefront_order(
            order=order, target_status=StorefrontOrder.Status.CONFIRMED, actor=self.staff,
        )
        order.refresh_from_db()
        order.expires_at = timezone.now() - timedelta(seconds=1)
        order.save(update_fields=("expires_at",))

        self.assertEqual(expire_due_storefront_orders(), 0)
        self.assertEqual(available_stock_for_product(self.product), Decimal("3.000"))
        self.assertEqual(StorefrontOrder.objects.get(pk=order.pk).status, StorefrontOrder.Status.CONFIRMED)

    def test_staff_cannot_confirm_an_order_after_its_hold_expired(self):
        order = self._create_order()
        order.expires_at = timezone.now() - timedelta(seconds=1)
        order.save(update_fields=("expires_at",))

        transitioned = transition_storefront_order(
            order=order, target_status=StorefrontOrder.Status.CONFIRMED, actor=self.staff,
        )
        self.assertEqual(transitioned.status, StorefrontOrder.Status.EXPIRED)
        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))
