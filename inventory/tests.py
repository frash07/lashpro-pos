from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from sales.services import checkout_sale
from .models import InventoryMovement, ServiceConsumable, StockAdjustmentRequest
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


class InventoryAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username="inventory-admin",
            email="inventory-admin@example.test",
            password="test-password",
            role=User.Role.OWNER,
        )
        cls.requester = User.objects.create_user(
            username="inventory-requester",
            password="test-password",
            role=User.Role.CASHIER,
        )
        cls.product = Product.objects.create(
            sku="ADMIN-STOCK-1",
            name="Admin Glue",
            cost_price=Decimal("100.00"),
            selling_price=Decimal("250.00"),
            on_hand=Decimal("2.000"),
            reorder_level=Decimal("1.000"),
        )
        cls.service = Service.objects.create(
            name="Admin Classic Set",
            duration_minutes=90,
            price=Decimal("2500.00"),
        )
        cls.consumable = ServiceConsumable.objects.create(
            service=cls.service,
            product=cls.product,
            quantity_per_service=Decimal("0.250"),
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_inventory_movement_admin_is_read_only_and_searchable(self):
        movement = receive_stock(
            product=self.product,
            quantity="1.000",
            unit_cost="100.00",
            reason="Admin test receipt",
            actor=self.admin_user,
        )
        changelist = self.client.get(
            "/admin/inventory/inventorymovement/",
            {"q": "Admin Glue", "movement_type": "PURCHASE"},
        )
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, "Admin Glue")

        change_url = reverse("admin:inventory_inventorymovement_change", args=[movement.pk])
        detail = self.client.get(change_url)
        self.assertEqual(detail.status_code, 200)

        movement_admin = admin.site._registry[InventoryMovement]
        self.assertEqual(
            set(movement_admin.get_readonly_fields(None, movement)),
            {field.name for field in InventoryMovement._meta.fields},
        )
        self.assertFalse(movement_admin.has_add_permission(None))
        self.assertFalse(movement_admin.has_delete_permission(None, movement))

    def test_stock_adjustment_admin_creation_uses_audited_domain_service(self):
        response = self.client.post(
            reverse("admin:inventory_stockadjustmentrequest_add"),
            {
                "product": str(self.product.pk),
                "quantity_delta": "3.000",
                "reason": "Admin-created stock count correction",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)

        adjustment = StockAdjustmentRequest.objects.get(
            reason="Admin-created stock count correction"
        )
        self.assertEqual(adjustment.requested_by, self.admin_user)
        self.assertEqual(adjustment.status, StockAdjustmentRequest.Status.PENDING)
        self.assertTrue(
            AuditEvent.objects.filter(
                event_type=AuditEvent.EventType.APPROVAL,
                object_type="stock_adjustment",
                object_id=str(adjustment.pk),
                actor=self.admin_user,
            ).exists()
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("2.000"))

    def test_existing_adjustment_is_read_only_and_cannot_be_deleted_in_admin(self):
        adjustment = request_stock_adjustment(
            product=self.product,
            quantity_delta="1.000",
            reason="Protect submitted request",
            requested_by=self.requester,
        )
        change_url = reverse(
            "admin:inventory_stockadjustmentrequest_change",
            args=[adjustment.pk],
        )
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)

        adjustment_admin = admin.site._registry[StockAdjustmentRequest]
        self.assertEqual(
            set(adjustment_admin.get_readonly_fields(None, adjustment)),
            {field.name for field in StockAdjustmentRequest._meta.fields},
        )
        self.assertFalse(adjustment_admin.has_delete_permission(None, adjustment))

    def test_stock_adjustment_admin_action_uses_approval_service(self):
        adjustment = request_stock_adjustment(
            product=self.product,
            quantity_delta="3.000",
            reason="Manager-approved count correction",
            requested_by=self.requester,
        )
        response = self.client.post(
            reverse("admin:inventory_stockadjustmentrequest_changelist"),
            {
                "action": "approve_adjustments",
                "_selected_action": [str(adjustment.pk)],
                "index": "0",
            },
        )
        self.assertEqual(response.status_code, 302)

        adjustment.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(adjustment.status, StockAdjustmentRequest.Status.APPROVED)
        self.assertEqual(adjustment.reviewed_by, self.admin_user)
        self.assertEqual(self.product.on_hand, Decimal("5.000"))
        self.assertTrue(
            InventoryMovement.objects.filter(
                source_adjustment=adjustment,
                movement_type=InventoryMovement.Type.ADJUSTMENT,
                actor=self.admin_user,
            ).exists()
        )

    def test_service_consumable_admin_list_and_search_work(self):
        response = self.client.get(
            reverse("admin:inventory_serviceconsumable_changelist"),
            {"q": "Admin Classic Set"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Classic Set")
        self.assertContains(response, "Admin Glue")


    def test_cashier_with_admin_change_permission_cannot_approve_adjustment(self):
        cashier_staff = User.objects.create_user(
            username="inventory-cashier-admin",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )
        change_permission = Permission.objects.get(
            content_type__app_label="inventory",
            codename="change_stockadjustmentrequest",
        )
        cashier_staff.user_permissions.add(change_permission)

        adjustment = request_stock_adjustment(
            product=self.product,
            quantity_delta="3.000",
            reason="Cashier must not approve",
            requested_by=self.requester,
        )
        self.client.force_login(cashier_staff)
        response = self.client.post(
            reverse("admin:inventory_stockadjustmentrequest_changelist"),
            {
                "action": "approve_adjustments",
                "_selected_action": [str(adjustment.pk)],
                "index": "0",
            },
        )
        self.assertEqual(response.status_code, 302)

        adjustment.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(adjustment.status, StockAdjustmentRequest.Status.PENDING)
        self.assertIsNone(adjustment.reviewed_by)
        self.assertEqual(self.product.on_hand, Decimal("2.000"))
        self.assertFalse(
            InventoryMovement.objects.filter(source_adjustment=adjustment).exists()
        )
