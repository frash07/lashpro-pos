from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from catalog.models import Product
from commissions.models import CommissionLedgerEntry, CommissionPayoutRecord
from inventory.models import InventoryMovement
from payments.models import CashSession, PaymentTransaction, RefundPayout, SalePayment
from sales.models import Sale, SaleLine, SaleRefund
from .forms import ReportDateFilterForm

ZERO = Decimal("0.00")


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))["total"] or ZERO


@login_required(login_url="login")
def daily_report(request):
    if not (request.user.is_superuser or getattr(request.user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise PermissionDenied
    today = timezone.localdate()
    form = ReportDateFilterForm(request.GET or {"start_date": today, "end_date": today})
    if form.is_valid():
        start, end = form.cleaned_data["start_date"], form.cleaned_data["end_date"]
    else:
        start = end = today

    sales_filter = {"sale__status": Sale.Status.COMPLETED, "sale__created_at__date__range": (start, end)}
    sale_line_total = ExpressionWrapper(
        F("quantity") * F("unit_price") - F("discount"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    completed_sales = Sale.objects.filter(status=Sale.Status.COMPLETED, created_at__date__range=(start, end))
    gross_sales = _sum(SaleLine.objects.filter(**sales_filter).annotate(line_total=sale_line_total), "line_total")

    cash_received = _sum(SalePayment.objects.filter(
        payment_transaction__method=PaymentTransaction.Method.CASH,
        payment_transaction__status=PaymentTransaction.Status.SUCCEEDED,
        payment_transaction__created_at__date__range=(start, end),
    ), "amount")
    verified_mpesa_received = _sum(SalePayment.objects.filter(
        payment_transaction__method=PaymentTransaction.Method.MPESA,
        payment_transaction__status=PaymentTransaction.Status.SUCCEEDED,
        payment_transaction__reconciliation__decision="CONFIRMED",
        payment_transaction__reconciliation__reconciled_at__date__range=(start, end),
    ), "amount")
    confirmed_collection = cash_received + verified_mpesa_received
    unverified_collection = _sum(SalePayment.objects.filter(
        payment_transaction__method=PaymentTransaction.Method.MPESA,
        payment_transaction__status=PaymentTransaction.Status.UNVERIFIED,
        payment_transaction__created_at__date__range=(start, end),
    ), "amount")

    refund_payouts = RefundPayout.objects.all()
    cash_refunds = refund_payouts.filter(method="CASH", issued_at__date__range=(start, end))
    verified_mpesa_refunds = refund_payouts.filter(
        method="MPESA", payout_reconciliation__decision="CONFIRMED",
        payout_reconciliation__reconciled_at__date__range=(start, end),
    )
    confirmed_refunds = _sum(cash_refunds | verified_mpesa_refunds, "amount")
    unverified_refunds = _sum(refund_payouts.filter(method="MPESA", payout_reconciliation__isnull=True, issued_at__date__range=(start, end)), "amount")
    rejected_refunds = _sum(refund_payouts.filter(
        method="MPESA", payout_reconciliation__decision="REJECTED",
        payout_reconciliation__reconciled_at__date__range=(start, end),
    ), "amount")
    issued_refunds = SaleRefund.objects.filter(status=SaleRefund.Status.ISSUED, reviewed_at__date__range=(start, end))

    ledger = CommissionLedgerEntry.objects.filter(created_at__date__range=(start, end))
    commission_earned = _sum(ledger.filter(entry_type=CommissionLedgerEntry.Type.EARNED), "amount")
    commission_reversed = abs(_sum(ledger.filter(entry_type=CommissionLedgerEntry.Type.REVERSAL), "amount"))
    commission_payouts = CommissionPayoutRecord.objects.filter(issued_at__date__range=(start, end))
    commission_payout_total = _sum(commission_payouts, "amount")
    commission_payout_unverified = _sum(commission_payouts.filter(method="MPESA", payout_reconciliation__isnull=True), "amount")

    movements = InventoryMovement.objects.filter(created_at__date__range=(start, end)).values("movement_type").annotate(
        quantity=Sum("quantity_delta"), count=Count("pk"),
    ).order_by("movement_type")
    movement_summary = [
        {"type": InventoryMovement.Type(row["movement_type"]).label, "quantity": row["quantity"], "count": row["count"]}
        for row in movements
    ]
    low_stock = list(Product.objects.filter(
        active=True, reorder_level__gt=0, on_hand__lte=F("reorder_level"),
    ).order_by("on_hand", "name")[:50])
    sessions_opened = CashSession.objects.filter(opened_at__date__range=(start, end))
    closed_sessions = CashSession.objects.filter(status=CashSession.Status.CLOSED, closed_at__date__range=(start, end))
    sessions_awaiting_review = CashSession.objects.filter(status=CashSession.Status.PENDING_APPROVAL, closed_at__date__range=(start, end))
    report = {
        "completed_sale_count": completed_sales.count(),
        "gross_sales": gross_sales,
        "confirmed_collection": confirmed_collection,
        "unverified_collection": unverified_collection,
        "confirmed_refunds": confirmed_refunds,
        "unverified_refunds": unverified_refunds,
        "rejected_refunds": rejected_refunds,
        "net_confirmed_collection": confirmed_collection - confirmed_refunds,
        "issued_refund_count": issued_refunds.count(),
        "commission_earned": commission_earned,
        "commission_reversed": commission_reversed,
        "commission_net": commission_earned - commission_reversed,
        "commission_payout_total": commission_payout_total,
        "commission_payout_unverified": commission_payout_unverified,
        "inventory_movement_summary": movement_summary,
        "low_stock": low_stock,
        "cash_session_count": sessions_opened.count(),
        "cash_session_variance_total": _sum(closed_sessions, "variance"),
        "cash_sessions_pending_approval": sessions_awaiting_review.count(),
    }
    return render(request, "reporting/dashboard.html", {"form": form, "report": report, "start": start, "end": end})
