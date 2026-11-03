from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from sales.models import Sale, SaleLine, SaleRefund
from catalog.models import Service
from .models import (
    CashSession,
    CashSessionMovement,
    PaymentReconciliation,
    PaymentTransaction,
    PayoutReconciliation,
    RefundPayout,
    SalePayment,
)
from .services import (
    add_cash_session_movement,
    open_cash_session,
    reconcile_manual_mpesa,
    reconcile_mpesa_payout,
)


class PaymentsCashAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username="payments-owner",
            email="payments-owner@example.test",
            password="test-password",
            role=User.Role.OWNER,
        )
        cls.manager = User.objects.create_user(
            username="payments-manager",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="payments-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )
        cls.service = Service.objects.create(
            name="Payments Admin Test Service",
            duration_minutes=60,
            price=Decimal("1500.00"),
        )
        # The database guard permits sale-line inserts only while the sale is draft.
        cls.sale = Sale.objects.create(cashier=cls.cashier)
        cls.sale_line = SaleLine.from_service(sale=cls.sale, service=cls.service)
        cls.sale_line.save()
        cls.sale.status = Sale.Status.COMPLETED
        cls.sale.save(update_fields=("status",))

        cls.payment = PaymentTransaction.objects.create(
            amount=Decimal("1500.00"),
            method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED,
            reference="ADMINPAYMENT001",
            recorded_by=cls.cashier,
        )
        cls.sale_payment = SalePayment.objects.create(
            sale=cls.sale,
            payment_transaction=cls.payment,
            amount=Decimal("1500.00"),
        )

        cls.cash_session = open_cash_session(
            cashier=cls.cashier,
            opening_float=Decimal("500.00"),
            actor=cls.cashier,
        )
        cls.cash_movement = add_cash_session_movement(
            session=cls.cash_session,
            movement_type=CashSessionMovement.Type.EXPENSE,
            amount=Decimal("-50.00"),
            reason="Admin integration test expense",
            actor=cls.owner,
        )

        cls.refund = SaleRefund.objects.create(
            sale=cls.sale,
            amount=Decimal("100.00"),
            method=SaleRefund.Method.MPESA,
            reference="REFUND-ADMIN-001",
            reason="Admin integration test refund",
            requested_by=cls.cashier,
            status=SaleRefund.Status.ISSUED,
            reviewed_by=cls.owner,
        )
        cls.refund_payout = RefundPayout.objects.create(
            refund=cls.refund,
            method=PaymentTransaction.Method.MPESA,
            amount=Decimal("100.00"),
            reference="REFUND-ADMIN-001",
            issued_by=cls.owner,
        )

        cls.manager.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="payments",
            codename__in=(
                "change_paymenttransaction",
                "change_salepayment",
                "view_paymentreconciliation",
                "view_cashsession",
                "view_cashsessionmovement",
                "view_refundpayout",
                "view_payoutreconciliation",
            ),
        ))

    def test_financial_admin_records_are_read_only_and_cannot_be_added_or_deleted(self):
        reconcile_manual_mpesa(
            payment=self.payment,
            actor=self.owner,
            decision=PaymentReconciliation.Decision.CONFIRMED,
            reason="Matched against the statement.",
        )
        reconcile_mpesa_payout(
            payout_type="REFUND",
            payout=self.refund_payout,
            actor=self.owner,
            decision=PayoutReconciliation.Decision.CONFIRMED,
            reason="Matched refund payout against the statement.",
        )

        records = (
            (PaymentTransaction, self.payment, "payments_paymenttransaction"),
            (SalePayment, self.sale_payment, "payments_salepayment"),
            (PaymentReconciliation, self.payment.reconciliation, "payments_paymentreconciliation"),
            (CashSession, self.cash_session, "payments_cashsession"),
            (CashSessionMovement, self.cash_movement, "payments_cashsessionmovement"),
            (RefundPayout, self.refund_payout, "payments_refundpayout"),
            (PayoutReconciliation, self.refund_payout.payout_reconciliation, "payments_payoutreconciliation"),
        )
        self.client.force_login(self.owner)

        for model, obj, admin_name in records:
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                change_url = reverse(f"admin:{admin_name}_change", args=[obj.pk])
                response = self.client.get(change_url)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(model_admin.has_add_permission(response.wsgi_request))
                self.assertFalse(model_admin.has_delete_permission(response.wsgi_request, obj))
                self.assertTrue(
                    {field.name for field in model._meta.fields}.issubset(
                        set(model_admin.get_readonly_fields(response.wsgi_request, obj))
                    )
                )
                self.assertEqual(
                    self.client.get(reverse(f"admin:{admin_name}_add")).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.get(reverse(f"admin:{admin_name}_delete", args=[obj.pk])).status_code,
                    403,
                )

    def test_manager_can_review_financial_records_but_cashier_cannot_open_finance_admin(self):
        self.client.force_login(self.manager)
        for url_name in (
            "payments_cashsession_changelist",
            "payments_cashsessionmovement_changelist",
            "payments_paymentreconciliation_changelist",
            "payments_refundpayout_changelist",
            "payments_payoutreconciliation_changelist",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(f"admin:{url_name}")).status_code, 200)

        self.client.force_login(self.cashier)
        for url_name in (
            "payments_paymentreconciliation_changelist",
            "payments_payoutreconciliation_changelist",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(f"admin:{url_name}")).status_code, 403)

    def test_payment_and_payout_reconciliations_are_immutable_and_audited(self):
        payment_reconciliation = reconcile_manual_mpesa(
            payment=self.payment,
            actor=self.owner,
            decision=PaymentReconciliation.Decision.CONFIRMED,
            reason="Confirmed using the M-Pesa statement.",
        )
        payout_reconciliation = reconcile_mpesa_payout(
            payout_type="REFUND",
            payout=self.refund_payout,
            actor=self.owner,
            decision=PayoutReconciliation.Decision.CONFIRMED,
            reason="Confirmed using the payout statement.",
        )

        self.assertEqual(payment_reconciliation.reference_snapshot, self.payment.reference)
        self.assertEqual(payout_reconciliation.reference_snapshot, self.refund_payout.reference)
        with self.assertRaises(TypeError):
            payment_reconciliation.delete()
        with self.assertRaises(TypeError):
            payout_reconciliation.delete()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentTransaction.Status.SUCCEEDED)
