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
        raw_amount = Decimal(str(amount))
        amount = raw_amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid KSh amount."}) from None
    if not raw_amount.is_finite() or raw_amount != amount or amount <= 0:
        raise ValidationError({"amount": "Enter an amount greater than zero with no more than two decimal places."})

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


@transaction.atomic
def settle_expense(*, expense, actor, payment_method, reference="", cash_session=None):
    if not _is_manager(actor):
        raise ValidationError({"actor": "Only an owner or manager may settle business expenses."})

    expense_id = expense.pk if isinstance(expense, Expense) else expense
    try:
        locked = Expense.objects.select_for_update().get(pk=expense_id)
    except (Expense.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"expense": "Choose a valid expense to settle."}) from None

    if locked.payment_status != Expense.PaymentStatus.UNPAID:
        raise ValidationError({"expense": "This expense is not awaiting payment."})

    method = str(payment_method or "").upper()
    if method not in Expense.PaymentMethod.values:
        raise ValidationError({"payment_method": "Choose cash, M-Pesa or bank transfer."})

    movement = None
    session = None
    session_id = getattr(cash_session, "pk", cash_session)
    normalized_reference = str(reference or "").strip().upper()

    if method == Expense.PaymentMethod.CASH:
        if not session_id:
            raise ValidationError({"cash_session": "Choose the open cash drawer used for this payment."})
        movement = add_cash_session_movement(
            session=session_id,
            movement_type=CashSessionMovement.Type.EXPENSE,
            amount=-locked.amount,
            reason=f"Settlement of expense #{locked.pk}: {locked.description}",
            actor=actor,
        )
        session = CashSession.objects.get(pk=session_id)
    elif session_id:
        raise ValidationError({"cash_session": "Only cash settlements can use a cash drawer."})

    locked.payment_status = Expense.PaymentStatus.PAID
    locked.payment_method = method
    locked.reference = normalized_reference
    locked.cash_session = session
    locked.cash_movement = movement
    locked.full_clean()
    locked.save(update_fields=(
        "payment_status", "payment_method", "reference", "cash_session", "cash_movement",
    ))

    record_audit_event(
        event_type=AuditEvent.EventType.EXPENSE,
        object_type="expense",
        object_id=locked.pk,
        actor=actor,
        reason=f"Settled expense: {locked.description}",
        before_state={"payment_status": Expense.PaymentStatus.UNPAID},
        after_state={
            "payment_status": locked.payment_status,
            "payment_method": locked.payment_method,
            "reference": locked.reference,
            "cash_session_id": locked.cash_session_id,
            "cash_movement_id": locked.cash_movement_id,
        },
        metadata={"amount": str(locked.amount), "expense_date": locked.expense_date.isoformat()},
    )
    return locked
