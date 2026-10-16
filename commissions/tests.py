from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from commissions.models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest
from commissions.services import approve_commission_payout, complete_service_line, request_commission_payout
from inventory.models import InventoryMovement, ServiceConsumable
from payments.services import reconcile_mpesa_payout
from sales.services import checkout_sale


class CommissionEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="commission-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="commission-manager", password="x", role=User.Role.MANAGER)
        cls.technician = User.objects.create_user(username="commission-tech", password="x", role=User.Role.TECHNICIAN)
        cls.glue = Product.objects.create(sku="CONS-1", name="Glue", cost_price=Decimal("100"), selling_price=Decimal("500"), on_hand=Decimal("5.000"))
        cls.service = Service.objects.create(name="Lash set", duration_minutes=60, price=Decimal("1000.00"), commission_eligible=True)
        ServiceConsumable.objects.create(service=cls.service, product=cls.glue, quantity_per_service=Decimal("0.500"))

    def test_service_completion_consumes_recipe_and_earns_commission(self):
        sale = checkout_sale(cashier=self.manager, items=[{"service_id": self.service.pk, "discount": "100.00", "discount_reason": "Manager-approved lash promotion."}])
        line = sale.lines.get()
        entry = complete_service_line(sale_line=line, technician=self.technician, actor=self.manager)
        self.glue.refresh_from_db()
        self.assertEqual(self.glue.on_hand, Decimal("4.500"))
        self.assertEqual(entry.base_amount, Decimal("900.00"))
        self.assertEqual(entry.amount, Decimal("360.00"))
        self.assertEqual(entry.rate_snapshot, Decimal("0.4000"))
        self.assertTrue(AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.SERVICE_COMPLETION,
            object_type="sale_line", object_id=str(line.pk),
        ).exists())
        self.assertEqual(InventoryMovement.objects.filter(sale_line=line, movement_type=InventoryMovement.Type.SERVICE_USE).count(), 1)

    def test_mpesa_commission_payout_stays_unverified_until_reconciled(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        line = sale.lines.get()
        complete_service_line(sale_line=line, technician=self.technician, actor=self.manager)
        request = request_commission_payout(technician=self.technician, amount="100.00", method="MPESA", reference="PAYOUT123", reason="Daily payout.", requested_by=self.technician)
        record = approve_commission_payout(payout=request, approver=self.manager)
        request.refresh_from_db()
        self.assertEqual(request.status, CommissionPayoutRequest.Status.ISSUED)
        self.assertEqual(record.verification_status, "UNVERIFIED")
        reconcile_mpesa_payout(payout_type="COMMISSION", payout=record, actor=self.manager, decision="CONFIRMED", reason="Matched to outgoing statement.")
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "CONFIRMED")
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION, object_type="commission_payout").exists())
        with self.assertRaises(TypeError):
            CommissionPayoutRecord.objects.filter(pk=record.pk).update(amount=Decimal("1.00"))
