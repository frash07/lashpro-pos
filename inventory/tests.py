from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product
from sales.services import checkout_sale
from .models import InventoryMovement, StockAdjustmentRequest
from .services import receive_stock, request_stock_adjustment, review_stock_adjustment


class InventoryServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="stock-cashier", password="x", role=User.Role.CASHIER)
        cls.owner = User.objects.create_user(username="stock-owner", password="x", role=User.Role.OWNER)
        cls.product = Product.objects.create(
            sku="STOCK-1", name="Glue", cost_price=Decimal("100"), selling_price=Decimal("250"),
            on_hand=Decimal("2.000"), reorder_level=Decimal("2.000"),
        )

    def test_product_sale_deducts_and_logs_immutable_movement(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"product_id": self.product.pk, "quantity": 1}])
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("1.000"))
        movement = InventoryMovement.objects.get(sale_line__sale=sale)
        self.assertEqual(movement.quantity_delta, Decimal("-1.000"))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEvent.EventType.SALE_STOCK_DEDUCTION).count(), 1)
        with self.assertRaises(TypeError):
            movement.delete()

    def test_adjustment_requires_separate_manager_approval_and_is_audited(self):
        request = request_stock_adjustment(
            product=self.product, quantity_delta="3", reason="Opening count", requested_by=self.cashier,
        )
        with self.assertRaises(ValidationError):
            review_stock_adjustment(adjustment=request, approver=self.cashier, approve=True)
        review_stock_adjustment(adjustment=request, approver=self.owner, approve=True)
        self.product.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(request.status, StockAdjustmentRequest.Status.APPROVED)
        self.assertEqual(self.product.on_hand, Decimal("5.000"))
        event = AuditEvent.objects.get(event_type=AuditEvent.EventType.STOCK_ADJUSTMENT)
        self.assertEqual(event.approver, self.owner)
        self.assertEqual(event.before_state["on_hand"], "2.000")

    def test_adjustment_cannot_reduce_stock_below_zero(self):
        request = request_stock_adjustment(
            product=self.product, quantity_delta="-3", reason="Count correction", requested_by=self.cashier,
        )
        with self.assertRaises(ValidationError):
            review_stock_adjustment(adjustment=request, approver=self.owner, approve=True)
        self.product.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("2.000"))
        self.assertEqual(request.status, StockAdjustmentRequest.Status.PENDING)

    def test_supplier_receipt_updates_stock_and_audit_ledger(self):
        movement = receive_stock(
            product=self.product, quantity="2.125", unit_cost="125.50",
            reason="Supplier delivery invoice 1042", actor=self.owner,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("4.125"))
        self.assertEqual(self.product.cost_price, Decimal("125.50"))
        self.assertEqual(movement.movement_type, InventoryMovement.Type.PURCHASE)
        self.assertEqual(movement.quantity_delta, Decimal("2.125"))
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.STOCK_ADJUSTMENT, object_id=str(movement.pk)).exists())

    def test_low_stock_uses_reorder_threshold(self):
        self.assertTrue(self.product.low_stock)
        self.product.on_hand = Decimal("2.001")
        self.assertFalse(self.product.low_stock)


class ConcurrentStockCheckoutTests(TransactionTestCase):
    reset_sequences = True

    def test_two_simultaneous_checkouts_cannot_sell_the_last_unit_twice(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks are required for this acceptance test.")
        cashier = User.objects.create_user(username="concurrent-cashier", password="x", role=User.Role.CASHIER)
        product = Product.objects.create(
            sku="LAST-UNIT", name="Last glue", cost_price=Decimal("10"),
            selling_price=Decimal("20"), on_hand=Decimal("1.000"),
        )
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                worker = User.objects.get(pk=cashier.pk)
                barrier.wait(timeout=10)
                checkout_sale(cashier=worker, items=[{"product_id": product.pk, "quantity": 1}])
                return "sold"
            except ValidationError:
                return "out_of_stock"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        product.refresh_from_db()
        self.assertCountEqual(results, ["sold", "out_of_stock"])
        self.assertEqual(product.on_hand, Decimal("0.000"))
        self.assertEqual(InventoryMovement.objects.filter(product=product, movement_type="SALE").count(), 1)
