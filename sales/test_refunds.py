from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.db.models import Sum

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from commissions.models import CommissionLedgerEntry
from commissions.services import complete_service_line
from inventory.models import InventoryMovement
from payments.models import CashSession, RefundPayout
from .models import SaleRefund
from .services import checkout_sale, issue_refund, request_sale_refund


class RefundFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="refund-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="refund-manager", password="x", role=User.Role.MANAGER)
        cls.technician = User.objects.create_user(username="refund-tech", password="x", role=User.Role.TECHNICIAN)
        CashSession.objects.create(cashier=cls.cashier, opened_by=cls.cashier)
        CashSession.objects.create(cashier=cls.manager, opened_by=cls.manager)
        cls.product = Product.objects.create(sku="RETURN-1", name="Adhesive", cost_price=Decimal("100.00"), selling_price=Decimal("500.00"), on_hand=Decimal("2.000"))
        cls.service = Service.objects.create(name="Full set", duration_minutes=90, price=Decimal("2000.00"), commission_rate=Decimal("0.4000"))

    def test_product_refund_requires_approval_and_restock_creates_ledger_entry(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"product_id": self.product.pk}], payments=[{"method": "CASH", "amount": "500.00"}])
        line = sale.lines.get()
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("1.000"))
        refund = request_sale_refund(sale=sale, items=[{"sale_line_id": line.pk, "quantity": 1, "restock": True}], method="CASH", reason="Customer returned unopened item.", requested_by=self.cashier)
        self.assertEqual(refund.status, SaleRefund.Status.REQUESTED)
        payout = issue_refund(refund=refund, approver=self.manager)
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("2.000"))
        self.assertEqual(payout.amount, Decimal("500.00"))
        self.assertEqual(payout.cash_session.cashier, self.manager)
        self.assertEqual(InventoryMovement.objects.filter(sale_line=line, movement_type=InventoryMovement.Type.RETURN).count(), 1)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.REFUND, object_type="sale_refund", object_id=str(refund.pk)).exists())

    def test_service_completion_earns_snapshot_rate_and_refund_reverses_commission(self):
        sale = checkout_sale(cashier=self.manager, items=[{"service_id": self.service.pk, "discount": "100.00", "discount_reason": "Manager-approved service adjustment."}], payments=[{"method": "CASH", "amount": "1900.00"}])
        line = sale.lines.get()
        self.service.commission_rate = Decimal("0.5000")
        self.service.save(update_fields=("commission_rate",))
        earned = complete_service_line(sale_line=line, technician=self.technician, actor=self.manager)
        self.assertEqual(line.commission_rate_snapshot, Decimal("0.4000"))
        self.assertEqual(earned.amount, Decimal("760.00"))
        refund = request_sale_refund(sale=sale, items=[{"sale_line_id": line.pk, "quantity": 1}], method="CASH", reason="Service refund approved.", requested_by=self.cashier)
        issue_refund(refund=refund, approver=self.manager)
        entries = CommissionLedgerEntry.objects.filter(sale_line=line)
        self.assertEqual(entries.count(), 2)
        self.assertEqual(entries.aggregate(total=Sum("amount"))["total"], Decimal("0.00"))
        self.assertEqual(RefundPayout.objects.get(refund=refund).verification_status, "CONFIRMED")

    def test_cashier_cannot_issue_own_refund(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"product_id": self.product.pk}], payments=[{"method": "CASH", "amount": "500.00"}])
        refund = request_sale_refund(sale=sale, items=[{"sale_line_id": sale.lines.get().pk, "quantity": 1}], method="CASH", reason="Return request.", requested_by=self.cashier)
        with self.assertRaises(ValidationError):
            issue_refund(refund=refund, approver=self.cashier)
