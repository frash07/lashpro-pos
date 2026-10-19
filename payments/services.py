from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from .models import CashSession, CashSessionMovement, PaymentReconciliation, PaymentTransaction, PayoutReconciliation, RefundPayout, SalePayment


@transaction.atomic
def reconcile_manual_mpesa(*, payment, actor, decision, reason):
    payment_id = payment.pk if isinstance(payment, PaymentTransaction) else payment
    try:
        locked = PaymentTransaction.objects.select_for_update().get(pk=payment_id)
    except (PaymentTransaction.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"payment": "Payment transaction not found."}) from None
    if not (actor.is_superuser or getattr(actor, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise ValidationError({"actor": "Only an owner or manager may reconcile M-Pesa."})
    if locked.method != PaymentTransaction.Method.MPESA:
        raise ValidationError({"payment": "Only M-Pesa payments can be reconciled here."})
    if locked.status != PaymentTransaction.Status.UNVERIFIED:
        raise ValidationError({"payment": "This payment is not awaiting reconciliation."})
    decision = str(decision).upper()
    if decision not in PaymentReconciliation.Decision.values:
        raise ValidationError({"decision": "Choose confirm or reject."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record the statement match or reason for rejection."})

    before = locked.status
    after = (
        PaymentTransaction.Status.SUCCEEDED
        if decision == PaymentReconciliation.Decision.CONFIRMED
        else PaymentTransaction.Status.FAILED
    )
    reconciliation = PaymentReconciliation(
        payment_transaction=locked, decision=decision, reference_snapshot=locked.reference,
        reason=reason, reconciled_by=actor,
    )
    reconciliation.full_clean()
    reconciliation.save()
    locked.status = after
    locked.save(update_fields=("status",))
    allocation = getattr(locked, "sale_allocation", None)
    record_audit_event(
        event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION,
        object_type="payment_transaction", object_id=locked.pk,
        actor=actor, reason=reason,
        before_state={"status": before}, after_state={"status": after, "decision": decision},
        metadata={
            "reference": locked.reference,
            "sale_id": allocation.sale_id if allocation else None,
            "amount": str(locked.amount),
        },
    )
    allocation_sale = allocation.sale if allocation else None
    enrollment = None
    if allocation_sale:
        from training.models import Enrollment
        enrollment = Enrollment.objects.filter(sale=allocation_sale).first()
    if enrollment:
        from training.services import sync_enrollment_payment_status
        sync_enrollment_payment_status(enrollment)
    return reconciliation


from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


def _cash_money(value, *, allow_zero=False, signed=False):
    try:
        amount = Decimal(str(value))
        rounded = amount.quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid KSh amount."}) from None
    if not amount.is_finite() or amount != rounded or (not allow_zero and rounded == ZERO) or (not signed and rounded < ZERO):
        raise ValidationError({"amount": "Enter a valid amount with at most two decimal places."})
    return rounded


@transaction.atomic
def open_cash_session(*, cashier, opening_float, actor):
    cashier_id = cashier.pk if isinstance(cashier, User) else cashier
    try:
        cashier = User.objects.select_for_update().get(pk=cashier_id, is_active=True)
    except (User.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"cashier": "Choose an active staff member."}) from None
    if cashier.role not in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}:
        raise ValidationError({"cashier": "Only an owner, manager, or cashier can open a cash session."})
    if not _manager(actor) and actor.pk != cashier.pk:
        raise ValidationError({"actor": "You may open a session only for yourself."})
    opening_float = _cash_money(opening_float, allow_zero=True)
    if CashSession.objects.filter(cashier=cashier, status__in=(CashSession.Status.OPEN, CashSession.Status.PENDING_APPROVAL)).exists():
        raise ValidationError({"cashier": "This cashier already has an active or unapproved session."})
    session = CashSession.objects.create(cashier=cashier, opened_by=actor, opening_float=opening_float)
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="cash_session",
        object_id=session.pk, actor=actor, reason="Cash session opened.",
        after_state={"status": session.status, "opening_float": str(opening_float)},
        metadata={"cashier_id": cashier.pk},
    )
    return session


def calculate_expected_cash(session):
    session_obj = session if isinstance(session, CashSession) else CashSession.objects.get(pk=session)
    received = SalePayment.objects.filter(
        payment_transaction__cash_session=session_obj,
        payment_transaction__method=PaymentTransaction.Method.CASH,
        payment_transaction__status=PaymentTransaction.Status.SUCCEEDED,
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    refunds = RefundPayout.objects.filter(cash_session=session_obj, method=PaymentTransaction.Method.CASH).aggregate(total=Sum("amount"))["total"] or ZERO
    from commissions.models import CommissionPayoutRecord
    payouts = CommissionPayoutRecord.objects.filter(cash_session=session_obj, method="CASH").aggregate(total=Sum("amount"))["total"] or ZERO
    movements = CashSessionMovement.objects.filter(session=session_obj).aggregate(total=Sum("amount"))["total"] or ZERO
    return (session_obj.opening_float + received - refunds - payouts + movements).quantize(CENT)


@transaction.atomic
def add_cash_session_movement(*, session, movement_type, amount, reason, actor):
    session_id = session.pk if isinstance(session, CashSession) else session
    try:
        locked = CashSession.objects.select_for_update().get(pk=session_id, status=CashSession.Status.OPEN)
    except (CashSession.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"session": "Choose an open cash session."}) from None
    if not _manager(actor):
        raise ValidationError({"actor": "Only an owner or manager can record cash expenses or adjustments."})
    try:
        movement_type = CashSessionMovement.Type(str(movement_type).upper())
    except ValueError:
        raise ValidationError({"movement_type": "Choose an expense, authorized cash-in, or cash-out."}) from None
    amount = _cash_money(amount, signed=True)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Give a reason for this cash movement."})
    if movement_type == CashSessionMovement.Type.CASH_IN and amount <= ZERO:
        raise ValidationError({"amount": "Cash-in amount must be positive."})
    if movement_type in {CashSessionMovement.Type.EXPENSE, CashSessionMovement.Type.CASH_OUT} and amount >= ZERO:
        raise ValidationError({"amount": "Expense and cash-out amounts must be negative."})
    movement = CashSessionMovement.objects.create(session=locked, movement_type=movement_type, amount=amount, reason=reason, actor=actor)
    record_audit_event(
        event_type=AuditEvent.EventType.PAYOUT if amount < ZERO else AuditEvent.EventType.APPROVAL,
        object_type="cash_session_movement", object_id=movement.pk, actor=actor,
        reason=reason, after_state={"amount": str(amount), "movement_type": movement_type},
        metadata={"session_id": locked.pk, "cashier_id": locked.cashier_id},
    )
    return movement


@transaction.atomic
def close_cash_session(*, session, counted_cash, actor, reason=""):
    session_id = session.pk if isinstance(session, CashSession) else session
    try:
        locked = CashSession.objects.select_for_update().get(pk=session_id, status=CashSession.Status.OPEN)
    except (CashSession.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"session": "Choose an open cash session."}) from None
    if not _manager(actor) and actor.pk != locked.cashier_id:
        raise ValidationError({"actor": "Only this cashier or a manager can close the session."})
    counted, reason = _cash_money(counted_cash, allow_zero=True), (reason or "").strip()
    expected = calculate_expected_cash(locked)
    variance = (counted - expected).quantize(CENT)
    if variance != ZERO and not reason:
        raise ValidationError({"reason": "Explain the cash variance before submitting the close."})
    locked.expected_cash, locked.counted_cash, locked.variance = expected, counted, variance
    locked.close_reason, locked.closed_by, locked.closed_at = reason, actor, timezone.now()
    locked.status = CashSession.Status.PENDING_APPROVAL if variance else CashSession.Status.CLOSED
    locked.save(update_fields=("expected_cash", "counted_cash", "variance", "close_reason", "closed_by", "closed_at", "status"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="cash_session", object_id=locked.pk,
        actor=actor, reason=reason or "Cash session closed with no variance.",
        before_state={"status": CashSession.Status.OPEN},
        after_state={"status": locked.status, "expected_cash": str(expected), "counted_cash": str(counted), "variance": str(variance)},
        metadata={"cashier_id": locked.cashier_id},
    )
    return locked


@transaction.atomic
def approve_cash_session_close(*, session, approver, reason):
    session_id = session.pk if isinstance(session, CashSession) else session
    try:
        locked = CashSession.objects.select_for_update().get(pk=session_id, status=CashSession.Status.PENDING_APPROVAL)
    except (CashSession.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"session": "Choose a cash session awaiting approval."}) from None
    if not _manager(approver) or locked.closed_by_id == approver.pk:
        raise ValidationError({"approver": "A different owner or manager must approve this cash variance."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record the manager's review."})
    locked.status, locked.approved_by = CashSession.Status.CLOSED, approver
    locked.approval_reason, locked.approved_at = reason, timezone.now()
    locked.save(update_fields=("status", "approved_by", "approval_reason", "approved_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="cash_session", object_id=locked.pk,
        actor=locked.closed_by, approver=approver, reason=reason,
        before_state={"status": CashSession.Status.PENDING_APPROVAL, "variance": str(locked.variance)},
        after_state={"status": locked.status}, metadata={"cashier_id": locked.cashier_id},
    )
    return locked


@transaction.atomic
def reconcile_mpesa_payout(*, payout_type, payout, actor, decision, reason):
    from commissions.models import CommissionPayoutRecord
    if not _manager(actor):
        raise ValidationError({"actor": "Only an owner or manager may reconcile M-Pesa payouts."})
    payout_type = str(payout_type).upper()
    target_id = payout.pk if hasattr(payout, "pk") else payout
    if payout_type == "REFUND":
        model, field, object_type = RefundPayout, "refund_payout", "refund_payout"
    elif payout_type == "COMMISSION":
        model, field, object_type = CommissionPayoutRecord, "commission_payout", "commission_payout"
    else:
        raise ValidationError({"payout_type": "Choose a refund or commission payout."})
    try:
        locked = model.objects.select_for_update().get(pk=target_id)
    except (model.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"payout": "Payout record not found."}) from None
    if locked.method != "MPESA":
        raise ValidationError({"payout": "Only M-Pesa payouts need reference reconciliation."})
    if PayoutReconciliation.objects.filter(**{field: locked}).exists():
        raise ValidationError({"payout": "This payout has already been reconciled."})
    decision = str(decision).upper()
    if decision not in PayoutReconciliation.Decision.values:
        raise ValidationError({"decision": "Choose confirm or reject."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record the statement match or reason for rejection."})
    reconciliation = PayoutReconciliation(
        **{field: locked}, decision=decision, reference_snapshot=locked.reference,
        reason=reason, reconciled_by=actor,
    )
    reconciliation.full_clean()
    reconciliation.save()
    record_audit_event(
        event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION,
        object_type=object_type, object_id=locked.pk, actor=actor, reason=reason,
        before_state={"verification_status": "UNVERIFIED"}, after_state={"verification_status": decision},
        metadata={"reference": locked.reference, "amount": str(locked.amount)},
    )
    return reconciliation

@transaction.atomic
def cancel_abandoned_pending_payment(*, payment, actor, reason):
    """Cancel a manager-reviewed, unallocated legacy cash entry and audit it."""
    payment_id = payment.pk if isinstance(payment, PaymentTransaction) else payment
    if not getattr(actor, "is_active", False) or not _manager(actor):
        raise ValidationError({"actor": "Only an active owner or manager may cancel an abandoned payment."})
    try:
        locked = PaymentTransaction.objects.select_for_update().get(pk=payment_id)
    except (PaymentTransaction.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"payment": "Payment transaction not found."}) from None
    if locked.status != PaymentTransaction.Status.PENDING:
        raise ValidationError({"payment": "Only a pending payment can be cancelled."})
    if locked.method != PaymentTransaction.Method.CASH:
        raise ValidationError({"payment": "Only an abandoned cash entry can be cancelled here."})
    if locked.cash_session_id:
        raise ValidationError({"payment": "A payment linked to a cash session cannot be cancelled as abandoned."})
    if SalePayment.objects.filter(payment_transaction=locked).exists():
        raise ValidationError({"payment": "A payment allocated to a sale cannot be cancelled as abandoned."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record why this abandoned payment is being cancelled."})

    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="abandoned_payment",
        object_id=locked.pk,
        actor=actor,
        reason=reason,
        before_state={"status": locked.status},
        after_state={"status": PaymentTransaction.Status.CANCELLED},
        metadata={
            "payment_id": locked.pk,
            "method": locked.method,
            "amount": str(locked.amount),
            "reference_present": bool(locked.reference),
            "reference_length": len(locked.reference),
        },
    )
    locked.status = PaymentTransaction.Status.CANCELLED
    locked.save(update_fields=("status",))
    return locked
