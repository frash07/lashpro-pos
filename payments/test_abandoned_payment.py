from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from audit.models import AuditEvent
from payments.models import CashSession, PaymentTransaction, SalePayment
from payments.services import cancel_abandoned_pending_payment
from sales.models import Sale


class AbandonedPaymentCancellationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="abandoned-owner", password="x", role=User.Role.OWNER)
        cls.cashier = User.objects.create_user(username="abandoned-cashier", password="x", role=User.Role.CASHIER)

    def make_pending_cash(self, **kwargs):
        fields = {
            "amount": Decimal("125.00"),
            "method": PaymentTransaction.Method.CASH,
            "status": PaymentTransaction.Status.PENDING,
        }
        fields.update(kwargs)
        return PaymentTransaction.objects.create(**fields)

    def test_manager_cancels_only_unallocated_orphan_and_creates_audit(self):
        payment = self.make_pending_cash()
        result = cancel_abandoned_pending_payment(
            payment=payment, actor=self.owner,
            reason="User confirmed this was a test entry and authorized cancellation.",
        )
        payment.refresh_from_db()
        self.assertEqual(result.pk, payment.pk)
        self.assertEqual(payment.status, PaymentTransaction.Status.CANCELLED)
        event = AuditEvent.objects.get(object_type="abandoned_payment", object_id=str(payment.pk))
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.before_state, {"status": "PENDING"})
        self.assertEqual(event.after_state, {"status": "CANCELLED"})
        self.assertEqual(event.metadata["payment_id"], payment.pk)

    def test_cashier_cannot_cancel_and_blank_reason_is_rejected(self):
        payment = self.make_pending_cash()
        with self.assertRaises(ValidationError):
            cancel_abandoned_pending_payment(payment=payment, actor=self.cashier, reason="Test.")
        with self.assertRaises(ValidationError):
            cancel_abandoned_pending_payment(payment=payment, actor=self.owner, reason=" ")
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.PENDING)
        self.assertFalse(AuditEvent.objects.filter(object_type="abandoned_payment").exists())

    def test_non_cash_payment_cannot_use_cancellation_path(self):
        mpesa = self.make_pending_cash(method=PaymentTransaction.Method.MPESA, reference="TESTREF")
        with self.assertRaises(ValidationError):
            cancel_abandoned_pending_payment(payment=mpesa, actor=self.owner, reason="Test.")

    def test_cash_reference_is_preserved_and_its_presence_is_audited(self):
        payment = self.make_pending_cash(reference="T123")
        cancel_abandoned_pending_payment(payment=payment, actor=self.owner, reason="Test entry.")
        payment.refresh_from_db()
        event = AuditEvent.objects.get(object_type="abandoned_payment", object_id=str(payment.pk))
        self.assertEqual(payment.reference, "T123")
        self.assertEqual(payment.status, PaymentTransaction.Status.CANCELLED)
        self.assertEqual(event.metadata["reference_present"], True)
        self.assertEqual(event.metadata["reference_length"], 4)

    def test_session_linked_or_sale_allocated_payment_cannot_be_cancelled(self):
        session = CashSession.objects.create(cashier=self.owner, opened_by=self.owner)
        session_payment = self.make_pending_cash(cash_session=session)
        with self.assertRaises(ValidationError):
            cancel_abandoned_pending_payment(payment=session_payment, actor=self.owner, reason="Test.")

        payment = self.make_pending_cash()
        sale = Sale.objects.create(cashier=self.owner)
        SalePayment.objects.create(sale=sale, payment_transaction=payment, amount=payment.amount)
        with self.assertRaises(ValidationError):
            cancel_abandoned_pending_payment(payment=payment, actor=self.owner, reason="Test.")
