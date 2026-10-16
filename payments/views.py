from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from commissions.models import CommissionPayoutRecord
from .forms import CashSessionApprovalForm, CashSessionMovementForm, CloseCashSessionForm, OpenCashSessionForm
from .models import CashSession, PaymentTransaction, RefundPayout
from .services import (
    add_cash_session_movement, approve_cash_session_close, calculate_expected_cash,
    close_cash_session, open_cash_session, reconcile_manual_mpesa,
)


def _manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


def _can_use_cash_tools(user):
    return _manager(user) or getattr(user, "role", None) == User.Role.CASHIER


@login_required(login_url="login")
def reconciliation_queue(request):
    if not _manager(request.user):
        raise PermissionDenied
    if request.method == "POST":
        reason = request.POST.get("reason", "")
        try:
            if request.POST.get("payout_id"):
                from .services import reconcile_mpesa_payout
                reconcile_mpesa_payout(payout_type=request.POST.get("payout_type", ""), payout=request.POST.get("payout_id"), actor=request.user, decision=request.POST.get("decision", ""), reason=reason)
                label = "M-Pesa payout"
            else:
                payment = get_object_or_404(PaymentTransaction, pk=request.POST.get("payment_id"))
                reconcile_manual_mpesa(payment=payment, actor=request.user, decision=request.POST.get("decision", ""), reason=reason)
                label = f"Payment {payment.reference}"
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"{label} reconciled.")
        return redirect("payments:reconciliation")
    pending = PaymentTransaction.objects.filter(method=PaymentTransaction.Method.MPESA, status=PaymentTransaction.Status.UNVERIFIED).select_related("sale_allocation__sale__customer").order_by("created_at")
    pending_refunds = RefundPayout.objects.filter(method="MPESA", payout_reconciliation__isnull=True).select_related("refund__sale")
    pending_commissions = CommissionPayoutRecord.objects.filter(method="MPESA", payout_reconciliation__isnull=True).select_related("technician")
    return render(request, "payments/reconciliation.html", {
        "pending_payments": pending,
        "pending_refund_payouts": pending_refunds,
        "pending_commission_payouts": pending_commissions,
    })


@login_required(login_url="login")
def cash_session_dashboard(request):
    if not _can_use_cash_tools(request.user):
        raise PermissionDenied
    own_session = CashSession.objects.filter(cashier=request.user, status__in=(CashSession.Status.OPEN, CashSession.Status.PENDING_APPROVAL)).first()
    action = request.POST.get("action", "") if request.method == "POST" else ""
    try:
        if request.method == "POST" and action == "open":
            open_cash_session(cashier=request.user, opening_float=request.POST.get("opening_float"), actor=request.user)
            messages.success(request, "Cash session opened.")
        elif request.method == "POST" and action == "close" and own_session:
            close_cash_session(session=own_session, counted_cash=request.POST.get("counted_cash"), actor=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, "Cash session close recorded.")
        elif request.method == "POST" and action == "approve" and _manager(request.user):
            pending = get_object_or_404(CashSession, pk=request.POST.get("session_id"), status=CashSession.Status.PENDING_APPROVAL)
            approve_cash_session_close(session=pending, approver=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, "Cash variance approved.")
        elif request.method == "POST" and action == "movement" and own_session:
            form = CashSessionMovementForm(request.POST)
            if not form.is_valid():
                raise ValidationError(form.errors.as_text())
            data = form.cleaned_data
            amount = data["amount"] if data["movement_type"] == "CASH_IN" else -data["amount"]
            add_cash_session_movement(session=own_session, movement_type=data["movement_type"], amount=amount, reason=data["reason"], actor=request.user)
            messages.success(request, "Cash movement recorded.")
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    return redirect("payments:cash-session") if request.method == "POST" else _render_cash_session(request, own_session)


def _render_cash_session(request, own_session):
    if own_session and own_session.status == CashSession.Status.OPEN:
        own_session.expected_now = calculate_expected_cash(own_session)
    pending_sessions = CashSession.objects.filter(status=CashSession.Status.PENDING_APPROVAL).select_related("cashier", "closed_by") if _manager(request.user) else CashSession.objects.none()
    return render(request, "payments/cash_session.html", {
        "session": own_session, "open_form": OpenCashSessionForm(),
        "close_form": CloseCashSessionForm(), "movement_form": CashSessionMovementForm(),
        "pending_sessions": pending_sessions, "approval_form": CashSessionApprovalForm(),
        "is_manager": _manager(request.user),
    })
