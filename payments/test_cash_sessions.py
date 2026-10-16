from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from catalog.models import Service
from sales.services import checkout_sale
from .models import CashSession, CashSessionMovement
from django.core.exceptions import ValidationError

from .services import (
    add_cash_session_movement, approve_cash_session_close, calculate_expected_cash,
    close_cash_session, open_cash_session,
)


class CashSessionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="till-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="till-manager", password="x", role=User.Role.MANAGER)
        cls.service = Service.objects.create(name="Classic", duration_minutes=60, price=Decimal("1000.00"))

    def test_expected_cash_reconciles_sales_expenses_and_closes(self):
        session = open_cash_session(cashier=self.cashier, opening_float="100.00", actor=self.cashier)
        checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}], payments=[{"method": "CASH", "amount": "500.00"}])
        add_cash_session_movement(session=session, movement_type="EXPENSE", amount="-50.00", reason="Approved supplies", actor=self.manager)
        self.assertEqual(calculate_expected_cash(session), Decimal("550.00"))
        closed = close_cash_session(session=session, counted_cash="550.00", actor=self.cashier)
        self.assertEqual(closed.status, CashSession.Status.CLOSED)
        self.assertEqual(closed.variance, Decimal("0.00"))

    def test_cash_variance_waits_for_independent_manager_approval(self):
        session = open_cash_session(cashier=self.cashier, opening_float="100.00", actor=self.cashier)
        pending = close_cash_session(session=session, counted_cash="90.00", actor=self.cashier, reason="Drawer short by ten.")
        self.assertEqual(pending.status, CashSession.Status.PENDING_APPROVAL)
        with self.assertRaises(ValidationError):
            approve_cash_session_close(session=pending, approver=self.cashier, reason="Self approval.")
        closed = approve_cash_session_close(session=pending, approver=self.manager, reason="Reviewed count and receipt log.")
        self.assertEqual(closed.status, CashSession.Status.CLOSED)
        self.assertEqual(closed.variance, Decimal("-10.00"))

    def test_cash_checkout_is_rejected_without_open_session(self):
        with self.assertRaises(ValidationError):
            checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}], payments=[{"method": "CASH", "amount": "100.00"}])

    def test_cash_session_movements_are_immutable(self):
        session = open_cash_session(cashier=self.cashier, opening_float="10.00", actor=self.cashier)
        movement = add_cash_session_movement(session=session, movement_type="CASH_OUT", amount="-1.00", reason="Bank drop", actor=self.manager)
        with self.assertRaises(TypeError):
            CashSessionMovement.objects.filter(pk=movement.pk).update(amount=Decimal("-2.00"))
