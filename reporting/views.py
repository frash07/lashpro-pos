from datetime import timedelta
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


def _masked_phone(phone):
    digits = "".join(character for character in (phone or "") if character.isdigit())
    if not digits:
        return "—"
    if digits.startswith("254") and len(digits) >= 12:
        return f"+254 {digits[3:6]}***{digits[-3:]}"
    if digits.startswith("0") and len(digits) >= 10:
        return f"+254 {digits[1:4]}***{digits[-3:]}"
    return f"{digits[:4]}***{digits[-3:]}" if len(digits) > 7 else "••••"


def _display_amount(amount):
    return f"{amount:,.2f}".rstrip("0").rstrip(".")


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

    service_lines = SaleLine.objects.filter(**sales_filter, service__isnull=False)
    retail_lines = SaleLine.objects.filter(**sales_filter, product__isnull=False)
    service_total = _sum(service_lines.annotate(line_total=sale_line_total), "line_total")
    retail_total = _sum(retail_lines.annotate(line_total=sale_line_total), "line_total")
    service_retail_total = service_total + retail_total
    service_percent = round(service_total * 100 / service_retail_total) if service_retail_total else 0
    retail_percent = 100 - service_percent if service_retail_total else 0
    top_service = service_lines.values("description").annotate(total=Sum(sale_line_total)).order_by("-total", "description").first()

    valid_payment_statuses = (PaymentTransaction.Status.SUCCEEDED, PaymentTransaction.Status.UNVERIFIED)
    period_allocations = SalePayment.objects.filter(
        sale__status=Sale.Status.COMPLETED,
        payment_transaction__created_at__date__range=(start, end),
        payment_transaction__status__in=valid_payment_statuses,
    )
    mpesa_volume = _sum(period_allocations.filter(payment_transaction__method=PaymentTransaction.Method.MPESA), "amount")
    payment_volume = _sum(period_allocations.filter(
        payment_transaction__method__in=(PaymentTransaction.Method.MPESA, PaymentTransaction.Method.CASH),
    ), "amount")
    mpesa_share = round(mpesa_volume * 100 / payment_volume) if payment_volume else 0

    audit_transactions = PaymentTransaction.objects.filter(
        method=PaymentTransaction.Method.MPESA,
        created_at__date__range=(start, end),
    ).select_related(
        "reconciliation", "sale_allocation__sale__customer",
    ).order_by("-created_at", "-pk")[:20]
    mpesa_audit_rows = []
    for payment in audit_transactions:
        sale_payment = getattr(payment, "sale_allocation", None)
        customer = sale_payment.sale.customer if sale_payment and sale_payment.sale_id else None
        if payment.status == PaymentTransaction.Status.SUCCEEDED:
            status_label, status_class = "SUCCESS", "success"
        elif payment.status == PaymentTransaction.Status.FAILED:
            status_label, status_class = "REJECTED", "danger"
        elif payment.status == PaymentTransaction.Status.UNVERIFIED:
            status_label, status_class = "PENDING", "warning"
        else:
            status_label, status_class = payment.get_status_display().upper(), "muted"
        amount = sale_payment.amount if sale_payment else payment.amount
        mpesa_audit_rows.append({
            "payment": payment,
            "phone": _masked_phone(customer.phone if customer else ""),
            "amount_display": _display_amount(amount),
            "status_label": status_label,
            "status_class": status_class,
        })

    period_length = (end - start).days + 1
    prior_start = start - timedelta(days=period_length)
    prior_end = end - timedelta(days=period_length)
    prior_sales = _sum(SaleLine.objects.filter(
        sale__status=Sale.Status.COMPLETED,
        sale__created_at__date__range=(prior_start, prior_end),
    ).annotate(line_total=sale_line_total), "line_total")
    if prior_sales:
        revenue_change = (gross_sales - prior_sales) * 100 / prior_sales
        revenue_trend = f"{revenue_change:+.1f}% vs " + ("yesterday" if period_length == 1 else "previous period")
        revenue_trend_class = "positive" if revenue_change >= 0 else "negative"
    elif gross_sales:
        revenue_trend, revenue_trend_class = "New revenue vs previous period", "positive"
    else:
        revenue_trend, revenue_trend_class = "No previous sales for comparison", "neutral"

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
    low_stock_count = Product.objects.filter(
        active=True, reorder_level__gt=0, on_hand__lte=F("reorder_level"),
    ).count()
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
    inventory_products = Product.objects.filter(active=True).order_by("name")[:100]
    return render(request, "reporting/dashboard.html", {
        "form": form,
        "report": report,
        "start": start,
        "end": end,
        "inventory_products": inventory_products,
        "low_stock_count": low_stock_count,
        "mpesa_audit_rows": mpesa_audit_rows,
        "executive": {
            "revenue_label": "Today's Total Revenue" if start == end == today else "Total Revenue",
            "revenue_display": f"KES {gross_sales:,.0f}",
            "revenue_trend": revenue_trend,
            "revenue_trend_class": revenue_trend_class,
            "mpesa_display": f"KES {mpesa_volume:,.0f}",
            "mpesa_share": mpesa_share,
            "service_percent": service_percent,
            "retail_percent": retail_percent,
            "top_service": top_service["description"] if top_service else "No service sales yet",
            "academy_connected": False,
        },
    })
