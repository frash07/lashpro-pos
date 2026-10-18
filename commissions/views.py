from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Sum
from decimal import Decimal

from accounts.models import User
from payments.models import CashSession
from .forms import CommissionPayoutForm
from .models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest
from .services import approve_commission_payout, available_commission, reject_commission_payout, request_commission_payout


def _manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


@login_required(login_url="login")
def commission_dashboard(request):
    is_manager = _manager(request.user)
    if not is_manager and request.user.role != User.Role.TECHNICIAN:
        raise PermissionDenied
    if request.method == "POST":
        action = request.POST.get("action", "request")
        try:
            if action == "request":
                technician = request.user if not is_manager else request.POST.get("technician")
                payout = request_commission_payout(
                    technician=technician, amount=request.POST.get("amount"), method=request.POST.get("method", ""),
                    reference=request.POST.get("reference", ""), reason=request.POST.get("reason", ""), requested_by=request.user,
                )
                messages.success(request, f"Commission payout request #{payout.pk} submitted.")
            elif action == "approve" and is_manager:
                session = CashSession.objects.filter(cashier=request.user, status=CashSession.Status.OPEN).first()
                approve_commission_payout(
                    payout=request.POST.get("payout_id"), approver=request.user, cash_session=session,
                    review_reason=request.POST.get("review_reason", ""),
                )
                messages.success(request, "Commission payout issued.")
            elif action == "reject" and is_manager:
                reject_commission_payout(payout=request.POST.get("payout_id"), approver=request.user, reason=request.POST.get("review_reason", ""))
                messages.success(request, "Commission payout request rejected.")
            else:
                raise PermissionDenied
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        return redirect("commissions:dashboard")

    technicians = User.objects.filter(role=User.Role.TECHNICIAN, is_active=True).order_by("first_name", "username")
    requests = CommissionPayoutRequest.objects.select_related("technician", "requested_by", "reviewed_by")
    records = CommissionPayoutRecord.objects.select_related("technician", "issued_by")
    technician_balances = []
    if not is_manager:
        requests = requests.filter(technician=request.user)
        records = records.filter(technician=request.user)
        ledger = CommissionLedgerEntry.objects.filter(technician=request.user).select_related("technician", "sale_line")
        balance = available_commission(technician=request.user)
    else:
        ledger = CommissionLedgerEntry.objects.select_related("technician", "sale_line")
        zero = Decimal("0.00")
        for technician in technicians:
            earned = CommissionLedgerEntry.objects.filter(
                technician=technician, entry_type=CommissionLedgerEntry.Type.EARNED,
            ).aggregate(total=Sum("amount"))["total"] or zero
            reversals = CommissionLedgerEntry.objects.filter(
                technician=technician, entry_type=CommissionLedgerEntry.Type.REVERSAL,
            ).aggregate(total=Sum("amount"))["total"] or zero
            paid = CommissionPayoutRecord.objects.filter(technician=technician).aggregate(
                total=Sum("amount")
            )["total"] or zero
            pending = CommissionPayoutRequest.objects.filter(
                technician=technician, status=CommissionPayoutRequest.Status.REQUESTED,
            ).aggregate(total=Sum("amount"))["total"] or zero
            technician_balances.append({
                "technician": technician,
                "earned": earned,
                "reversed": abs(reversals),
                "paid": paid,
                "pending": pending,
                "available": available_commission(technician=technician),
            })
        balance = None
    return render(request, "commissions/dashboard.html", {
        "is_manager": is_manager, "technicians": technicians,
        "payout_form": CommissionPayoutForm(), "payout_requests": requests[:100],
        "payout_records": records[:100], "ledger": ledger[:100], "available_balance": balance,
        "technician_balances": technician_balances,
    })
