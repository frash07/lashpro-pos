from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from payments.models import CashSessionMovement
from payments.services import open_cash_session
from .models import Expense
from .services import record_expense


class ExpenseRegisterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="expense-owner", password="test-password", role=User.Role.OWNER, is_staff=True)
        cls.manager = User.objects.create_user(username="expense-manager", password="test-password", role=User.Role.MANAGER, is_staff=True)
        cls.cashier = User.objects.create_user(username="expense-cashier", password="test-password", role=User.Role.CASHIER, is_staff=True)
        cls.session = open_cash_session(cashier=cls.cashier, opening_float=Decimal("1000.00"), actor=cls.cashier)
        cls.manager_session = open_cash_session(cashier=cls.manager, opening_float=Decimal("500.00"), actor=cls.manager)
        cls.today = timezone.localdate()

    def _expense(self, **overrides):
        data = {
            "actor": self.manager,
            "category": Expense.Category.SALON_SUPPLIES,
            "description": "Disposable applicators",
            "amount": Decimal("250.00"),
            "expense_date": self.today,
            "payment_status": Expense.PaymentStatus.PAID,
            "payment_method": Expense.PaymentMethod.CASH,
            "cash_session": self.session,
        }
        data.update(overrides)
        return record_expense(**data)

    def test_owner_manager_can_open_register_and_cashier_cannot(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("expenses:dashboard")).status_code, 200)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("expenses:dashboard")).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("expenses:dashboard")).status_code, 200)

    def test_cash_expense_is_linked_to_immutable_drawer_movement(self):
        expense = self._expense()
        movement = CashSessionMovement.objects.get(pk=expense.cash_movement_id)
        self.assertEqual(movement.amount, Decimal("-250.00"))
        self.assertEqual(movement.movement_type, CashSessionMovement.Type.EXPENSE)
        self.assertEqual(expense.cash_session_id, self.session.pk)
        self.assertEqual(expense.cash_movement_id, movement.pk)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.EXPENSE, object_id=str(expense.pk)).exists())

    def test_mpesa_expense_requires_reference_and_does_not_change_drawer(self):
        with self.assertRaises(ValidationError):
            self._expense(payment_method=Expense.PaymentMethod.MPESA, cash_session=None, reference="")
        expense = self._expense(payment_method=Expense.PaymentMethod.MPESA, cash_session=None, reference="QXY12345")
        self.assertIsNone(expense.cash_movement_id)
        self.assertEqual(CashSessionMovement.objects.count(), 0)

    def test_unpaid_expense_has_no_payment_method_or_drawer_movement(self):
        expense = self._expense(payment_status=Expense.PaymentStatus.UNPAID, payment_method="", cash_session=None)
        self.assertEqual(expense.payment_status, Expense.PaymentStatus.UNPAID)
        self.assertFalse(expense.cash_movement_id)
        self.assertEqual(CashSessionMovement.objects.count(), 0)

    def test_cash_session_expense_action_creates_expense_register_record(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("payments:cash-session"), {
            "action": "movement",
            "movement_type": CashSessionMovement.Type.EXPENSE,
            "amount": "75.00",
            "reason": "Staff refreshments",
        })
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(description="Staff refreshments")
        self.assertEqual(expense.category, Expense.Category.OTHER)
        self.assertEqual(expense.amount, Decimal("75.00"))
        self.assertEqual(expense.cash_session_id, self.manager_session.pk)
        self.assertEqual(expense.cash_movement.amount, Decimal("-75.00"))

    def test_cashier_cannot_record_expense_even_if_they_have_an_open_session(self):
        with self.assertRaises(ValidationError):
            self._expense(actor=self.cashier)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(CashSessionMovement.objects.count(), 0)

    def test_expense_records_cannot_be_edited_or_deleted(self):
        expense = self._expense()
        expense.description = "Changed description"
        with self.assertRaises(TypeError):
            expense.save()
        with self.assertRaises(TypeError):
            expense.delete()

    def test_register_filters_and_summaries(self):
        self._expense()
        self._expense(payment_status=Expense.PaymentStatus.UNPAID, payment_method="", cash_session=None, amount=Decimal("100.00"))
        self.client.force_login(self.manager)
        response = self.client.get(reverse("expenses:dashboard"), {"start_date": self.today.replace(day=1).isoformat(), "end_date": self.today.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], Decimal("350.00"))
        self.assertEqual(response.context["paid_total"], Decimal("250.00"))
        self.assertEqual(response.context["unpaid_total"], Decimal("100.00"))


class ExpenseAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(username="expense-admin", email="expense-admin@example.test", password="test-password", role=User.Role.OWNER)

    def test_expense_admin_is_read_only(self):
        from .admin import ExpenseAdmin
        model_admin = admin.site._registry[Expense]
        request = type("Request", (), {"user": self.owner})()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertEqual(set(model_admin.get_readonly_fields(request)), {field.name for field in Expense._meta.fields})
