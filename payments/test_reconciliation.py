from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Service
from payments.models import PaymentReconciliation, PaymentTransaction
from payments.services import reconcile_manual_mpesa
from sales.services import checkout_sale, record_sale_payment


class ManualMpesaReconciliationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="recon-cashier", password="x", role=User.Role.CASHIER)
        cls.owner = User.objects.create_user(username="recon-owner", password="x", role=User.Role.OWNER)
        cls.service = Service.objects.create(name="Classic", duration_minutes=60, price=Decimal("2500.00"))

    def setUp(self):
        self.sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        self.payment = record_sale_payment(
            sale=self.sale, method="MPESA", amount="2500.00", reference="QAB123XYZ",
        )

    def test_owner_confirms_payment_and_audit_records_status_change(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("payments:reconciliation"), {
            "payment_id": self.payment.pk, "decision": "CONFIRMED", "reason": "Matched to statement entry.",
        })
        self.assertRedirects(response, reverse("payments:reconciliation"))
        self.payment.refresh_from_db()
        self.sale.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentTransaction.Status.SUCCEEDED)
        self.assertEqual(self.sale.paid_amount, Decimal("2500.00"))
        self.assertEqual(PaymentReconciliation.objects.get().reference_snapshot, "QAB123XYZ")
        event = AuditEvent.objects.get(event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION)
        self.assertEqual(event.before_state["status"], "UNVERIFIED")
        self.assertEqual(event.after_state["status"], "SUCCEEDED")

    def test_reject_marks_reference_failed_without_counting_it_as_paid(self):
        reconciliation = reconcile_manual_mpesa(
            payment=self.payment, actor=self.owner, decision="REJECTED", reason="Not present on statement.",
        )
        self.payment.refresh_from_db()
        self.assertEqual(reconciliation.decision, PaymentReconciliation.Decision.REJECTED)
        self.assertEqual(self.payment.status, PaymentTransaction.Status.FAILED)
        self.assertEqual(self.sale.unverified_amount, Decimal("0.00"))
        self.assertEqual(self.sale.paid_amount, Decimal("0.00"))

    def test_cashier_cannot_reconcile_mpesa(self):
        with self.assertRaises(ValidationError):
            reconcile_manual_mpesa(
                payment=self.payment, actor=self.cashier, decision="CONFIRMED", reason="Checked.",
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentTransaction.Status.UNVERIFIED)

    def test_m_pesa_reference_cannot_be_reused_case_insensitively(self):
        another_sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        with self.assertRaises(ValidationError):
            record_sale_payment(
                sale=another_sale, method="MPESA", amount="100.00", reference="qab123xyz",
            )

    def test_reconciliation_queue_is_manager_only(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("payments:reconciliation")).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("payments:reconciliation")), "QAB123XYZ")
