from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from payments.models import CashSession, CashSessionMovement
from payments.services import add_cash_session_movement
from .models import Expense


def _is_manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


@transaction.atomic
def record_expense(*, actor, category, description, amount, expense_date,
                   supplier="", payment_status=Expense.PaymentStatus.PAID,
                   payment_method="", reference="", cash_session=None):
    if not _is_manager(actor):
        raise ValidationError({"actor": "Only an owner or manager may record business expenses."})

    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid KSh amount."}) from None
    if not amount.is_finite() or amount <= 0:
        raise ValidationError({"amount": "Expense amount must be greater than zero."})

    session_id = getattr(cash_session, "pk", cash_session)
    movement = None
    normalized_method = str(payment_method or "").upper()
    normalized_status = str(payment_status or "").upper()
    if normalized_status == Expense.PaymentStatus.PAID and normalized_method == Expense.PaymentMethod.CASH:
        if not session_id:
            raise ValidationError({"cash_session": "Choose the open cash drawer used for this expense."})
        movement = add_cash_session_movement(
            session=session_id,
            movement_type=CashSessionMovement.Type.EXPENSE,
            amount=-amount,
            reason=f"Expense: {str(description).strip()}",
            actor=actor,
        )
        cash_session = CashSession.objects.get(pk=session_id)
    else:
        cash_session = None

    expense = Expense(
        expense_date=expense_date, category=category,
        description=str(description).strip(), supplier=str(supplier or "").strip(),
        amount=amount, payment_status=normalized_status, payment_method=normalized_method,
        reference=str(reference or "").strip().upper(), cash_session=cash_session,
        cash_movement=movement, created_by=actor,
    )
    expense.full_clean()
    expense.save(force_insert=True)

    record_audit_event(
        event_type=AuditEvent.EventType.EXPENSE, object_type="expense",
        object_id=expense.pk, actor=actor, reason=expense.description,
        after_state={
            "category": expense.category, "amount": str(expense.amount),
            "payment_status": expense.payment_status, "payment_method": expense.payment_method,
            "expense_date": expense.expense_date.isoformat(),
        },
        metadata={
            "supplier": expense.supplier, "reference": expense.reference,
            "cash_session_id": expense.cash_session_id, "cash_movement_id": expense.cash_movement_id,
        },
    )
    return expense
