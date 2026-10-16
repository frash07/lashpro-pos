from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from payments.models import CashSession, PaymentTransaction, RefundPayout
from sales.models import SaleLine, SaleRefundLine
from .models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value):
    try:
        amount = Decimal(str(value))
        rounded = amount.quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid KSh amount."}) from None
    if not amount.is_finite() or amount != rounded or rounded <= ZERO:
        raise ValidationError({"amount": "Amount must be positive and have at most two decimal places."})
    return rounded


def _manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


@transaction.atomic
def complete_service_line(*, sale_line, technician, actor):
    line_id = sale_line.pk if isinstance(sale_line, SaleLine) else sale_line
    try:
        line = SaleLine.objects.select_for_update().select_related("sale").get(pk=line_id)
    except (SaleLine.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"sale_line": "Sale line not found."}) from None
    if not line.service_id:
        raise ValidationError({"sale_line": "Only a service line can be completed."})
    if line.sale.status != "COMPLETED":
        raise ValidationError({"sale_line": "The sale must be completed first."})
    if line.service_completed_at:
        raise ValidationError({"sale_line": "This service has already been completed."})
    if line.refund_lines.filter(refund__status__in=("REQUESTED", "ISSUED")).exists():
        raise ValidationError({"sale_line": "A refunded or refund-pending service cannot be completed."})
    technician_id = technician.pk if isinstance(technician, User) else technician
    try:
        assigned = User.objects.get(pk=technician_id, role=User.Role.TECHNICIAN, is_active=True)
    except (User.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"technician": "Choose an active lash technician."}) from None
    if line.technician_id and line.technician_id != assigned.pk:
        raise ValidationError({"technician": "Complete this service with its assigned technician."})
    if not _manager(actor) and (actor.pk != assigned.pk or actor.role != User.Role.TECHNICIAN or line.technician_id != assigned.pk):
        raise ValidationError({"actor": "Only the assigned technician or a manager can complete this service."})
    from inventory.services import consume_service_requirements
    consume_service_requirements(sale_line=line, actor=actor)
    was_unassigned = line.technician_id is None
    line.technician, line.completed_by, line.service_completed_at = assigned, actor, timezone.now()
    line.save(update_fields=("technician", "completed_by", "service_completed_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.SERVICE_COMPLETION,
        object_type="sale_line",
        object_id=line.pk,
        actor=actor,
        reason="Service marked complete.",
        before_state={"service_completed_at": None, "technician_id": None if was_unassigned else assigned.pk},
        after_state={
            "service_completed_at": line.service_completed_at.isoformat(),
            "technician_id": assigned.pk,
            "completed_by_id": actor.pk,
        },
        metadata={"sale_id": line.sale_id, "sale_line_id": line.pk},
    )
    entry = None
    base = line.line_total()
    if line.commission_eligible_snapshot and base > ZERO and line.commission_rate_snapshot > ZERO:
        amount = (base * line.commission_rate_snapshot).quantize(CENT, rounding=ROUND_HALF_UP)
        if amount > ZERO:
            entry = CommissionLedgerEntry.objects.create(
                entry_type=CommissionLedgerEntry.Type.EARNED, sale_line=line,
                technician=assigned, base_amount=base, rate_snapshot=line.commission_rate_snapshot,
                amount=amount, created_by=actor,
            )
            record_audit_event(
                event_type=AuditEvent.EventType.COMMISSION_ADJUSTMENT,
                object_type="commission_ledger_entry", object_id=entry.pk, actor=actor,
                reason="Commission earned when service was completed.",
                after_state={"entry_type": "EARNED", "amount": str(amount), "rate": str(line.commission_rate_snapshot)},
                metadata={"sale_id": line.sale_id, "sale_line_id": line.pk, "technician_id": assigned.pk},
            )
    return entry


@transaction.atomic
def reverse_commission_for_refund(*, refund_line, actor):
    refund_line_id = refund_line.pk if isinstance(refund_line, SaleRefundLine) else refund_line
    try:
        line = SaleRefundLine.objects.select_related("sale_line").get(pk=refund_line_id)
        locked_sale_line = SaleLine.objects.select_for_update().get(pk=line.sale_line_id)
    except (SaleRefundLine.DoesNotExist, SaleLine.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"refund_line": "Refund line not found."}) from None
    line.sale_line = locked_sale_line
    earned = CommissionLedgerEntry.objects.filter(sale_line=locked_sale_line, entry_type=CommissionLedgerEntry.Type.EARNED).first()
    if not earned:
        return None
    existing = CommissionLedgerEntry.objects.filter(refund_line=line, entry_type=CommissionLedgerEntry.Type.REVERSAL).first()
    if existing:
        return existing
    already_reversed = CommissionLedgerEntry.objects.filter(
        sale_line=locked_sale_line, entry_type=CommissionLedgerEntry.Type.REVERSAL,
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    remaining = earned.amount + already_reversed
    if remaining <= ZERO:
        return None
    approved_lines = SaleRefundLine.objects.filter(
        sale_line=line.sale_line, refund__status="ISSUED",
    ).exclude(pk=line.pk).aggregate(total=Sum("amount"))["total"] or ZERO
    original_total = locked_sale_line.line_total()
    if line.amount + approved_lines >= original_total:
        reverse_amount = remaining
    else:
        reverse_amount = (earned.amount * line.amount / original_total).quantize(CENT, rounding=ROUND_HALF_UP)
        reverse_amount = min(reverse_amount, remaining)
    if reverse_amount <= ZERO:
        return None
    entry = CommissionLedgerEntry.objects.create(
        entry_type=CommissionLedgerEntry.Type.REVERSAL, sale_line=locked_sale_line,
        refund_line=line, technician=earned.technician, base_amount=-line.amount,
        rate_snapshot=earned.rate_snapshot, amount=-reverse_amount, created_by=actor,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.COMMISSION_ADJUSTMENT,
        object_type="commission_ledger_entry", object_id=entry.pk, actor=actor,
        reason=f"Commission reversed for refund #{line.refund_id}.",
        before_state={"commission_balance": str(remaining)}, after_state={"commission_balance": str(remaining - reverse_amount)},
        metadata={"refund_id": line.refund_id, "sale_line_id": locked_sale_line.pk, "technician_id": earned.technician_id},
    )
    return entry


def available_commission(*, technician, include_pending=True):
    tech_id = technician.pk if isinstance(technician, User) else technician
    balance = CommissionLedgerEntry.objects.filter(technician_id=tech_id).aggregate(total=Sum("amount"))["total"] or ZERO
    paid = CommissionPayoutRecord.objects.filter(technician_id=tech_id).aggregate(total=Sum("amount"))["total"] or ZERO
    pending = ZERO
    if include_pending:
        pending = CommissionPayoutRequest.objects.filter(
            technician_id=tech_id, status=CommissionPayoutRequest.Status.REQUESTED,
        ).aggregate(total=Sum("amount"))["total"] or ZERO
    return balance - paid - pending


@transaction.atomic
def request_commission_payout(*, technician, amount, method, reference="", reason, requested_by):
    technician_id = technician.pk if isinstance(technician, User) else technician
    try:
        tech = User.objects.select_for_update().get(pk=technician_id, role=User.Role.TECHNICIAN, is_active=True)
    except (User.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"technician": "Choose an active lash technician."}) from None
    amount = _money(amount)
    try:
        method = CommissionPayoutRequest.Method(str(method).upper())
    except ValueError:
        raise ValidationError({"method": "Choose cash or M-Pesa."}) from None
    reference, reason = (reference or "").strip().upper(), (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Explain the commission payout."})
    if method == CommissionPayoutRequest.Method.MPESA and not reference:
        raise ValidationError({"reference": "Enter the M-Pesa payout reference."})
    if len(reference) > 50:
        raise ValidationError({"reference": "Reference must be 50 characters or fewer."})
    if method == CommissionPayoutRequest.Method.MPESA and (
        PaymentTransaction.objects.filter(method="MPESA", reference__iexact=reference).exists()
        or RefundPayout.objects.filter(method="MPESA", reference__iexact=reference).exists()
        or CommissionPayoutRecord.objects.filter(method="MPESA", reference__iexact=reference).exists()
    ):
        raise ValidationError({"reference": "This M-Pesa reference is already in use."})
    if not _manager(requested_by) and requested_by.pk != tech.pk:
        raise ValidationError({"requested_by": "You may request a payout only for yourself."})
    if amount > available_commission(technician=tech):
        raise ValidationError({"amount": "Payout exceeds the technician's available commission balance."})
    payout = CommissionPayoutRequest(
        technician=tech, amount=amount, method=method, reference=reference,
        reason=reason, requested_by=requested_by,
    )
    payout.full_clean()
    payout.save()
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="commission_payout_request",
        object_id=payout.pk, actor=requested_by, reason=reason,
        after_state={"status": payout.status, "amount": str(amount), "method": method},
        metadata={"technician_id": tech.pk},
    )
    return payout


@transaction.atomic
def approve_commission_payout(*, payout, approver, cash_session=None, review_reason=""):
    payout_id = payout.pk if isinstance(payout, CommissionPayoutRequest) else payout
    try:
        request = CommissionPayoutRequest.objects.select_for_update().get(pk=payout_id)
    except (CommissionPayoutRequest.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"payout": "Commission payout request not found."}) from None
    if request.status != CommissionPayoutRequest.Status.REQUESTED:
        raise ValidationError({"payout": "This payout request has already been reviewed."})
    if not _manager(approver):
        raise ValidationError({"approver": "Only an owner or manager can approve a payout."})
    if request.requested_by_id == approver.pk:
        raise ValidationError({"approver": "A different owner or manager must approve this payout."})
    User.objects.select_for_update().get(pk=request.technician_id)
    other_pending = CommissionPayoutRequest.objects.filter(
        technician_id=request.technician_id, status=CommissionPayoutRequest.Status.REQUESTED,
    ).exclude(pk=request.pk).aggregate(total=Sum("amount"))["total"] or ZERO
    balance = CommissionLedgerEntry.objects.filter(technician_id=request.technician_id).aggregate(total=Sum("amount"))["total"] or ZERO
    paid = CommissionPayoutRecord.objects.filter(technician_id=request.technician_id).aggregate(total=Sum("amount"))["total"] or ZERO
    if request.amount + other_pending + paid > balance:
        raise ValidationError({"amount": "The available commission balance changed before approval."})
    session = None
    if request.method == CommissionPayoutRequest.Method.CASH:
        session_id = cash_session.pk if isinstance(cash_session, CashSession) else cash_session
        try:
            session = CashSession.objects.select_for_update().get(pk=session_id, status=CashSession.Status.OPEN)
        except (CashSession.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"cash_session": "An open cash session is required for a cash payout."}) from None
    reason = (review_reason or request.reason).strip()
    record = CommissionPayoutRecord.objects.create(
        request=request, technician_id=request.technician_id, amount=request.amount,
        method=request.method, reference=request.reference, issued_by=approver, cash_session=session,
    )
    request.status, request.reviewed_by = CommissionPayoutRequest.Status.ISSUED, approver
    request.review_reason, request.reviewed_at = reason, timezone.now()
    request.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.PAYOUT, object_type="commission_payout_record",
        object_id=record.pk, actor=request.requested_by, approver=approver,
        reason=reason, before_state={"status": "REQUESTED"},
        after_state={"status": "ISSUED", "verification_status": record.verification_status, "amount": str(record.amount), "method": record.method},
        metadata={"technician_id": record.technician_id, "reference": record.reference, "cash_session_id": record.cash_session_id},
    )
    return record


@transaction.atomic
def reject_commission_payout(*, payout, approver, reason):
    payout_id = payout.pk if isinstance(payout, CommissionPayoutRequest) else payout
    try:
        request = CommissionPayoutRequest.objects.select_for_update().get(pk=payout_id)
    except (CommissionPayoutRequest.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"payout": "Commission payout request not found."}) from None
    if request.status != CommissionPayoutRequest.Status.REQUESTED:
        raise ValidationError({"payout": "This payout request has already been reviewed."})
    if not _manager(approver) or request.requested_by_id == approver.pk:
        raise ValidationError({"approver": "A different owner or manager must reject this payout."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record why the payout was rejected."})
    request.status, request.reviewed_by = CommissionPayoutRequest.Status.REJECTED, approver
    request.review_reason, request.reviewed_at = reason, timezone.now()
    request.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="commission_payout_request",
        object_id=request.pk, actor=request.requested_by, approver=approver,
        reason=reason, before_state={"status": "REQUESTED"}, after_state={"status": "REJECTED"},
        metadata={"technician_id": request.technician_id, "amount": str(request.amount)},
    )
    return request
