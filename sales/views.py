import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from accounts.models import User
from catalog.models import Product, Service
from .forms import BalancePaymentForm, CheckoutDetailsForm, LineFormSet, PaymentFormSet
from .models import Sale, SaleLine, SaleRefund
from .services import checkout_sale, issue_refund, record_sale_payment, reject_refund, request_sale_refund

ALLOWED_ROLES = {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}


def check_role(user):
    if not (user.is_superuser or getattr(user, "role", None) in ALLOWED_ROLES):
        raise PermissionDenied


@login_required(login_url="login")
def checkout(request):
    check_role(request.user)
    if request.method == "POST":
        details = CheckoutDetailsForm(request.POST)
        lines = LineFormSet(request.POST, prefix="items")
        payments_formset = PaymentFormSet(request.POST, prefix="payments")
        valid_details = details.is_valid()
        valid_lines = lines.is_valid()
        valid_payments = payments_formset.is_valid()
        if valid_details and valid_lines and valid_payments:
            items, payments = [], []
            for form in lines:
                row = form.cleaned_data
                if row.get("DELETE") or not (row.get("product") or row.get("service")):
                    continue
                item = {"quantity": row["quantity"], "discount": row.get("discount") or "0.00",
                        "discount_reason": row.get("discount_reason", "")}
                item["product_id" if row.get("product") else "service_id"] = (
                    row["product"].pk if row.get("product") else row["service"].pk)
                if row.get("service"):
                    item["technician_id"] = row["technician"].pk
                items.append(item)
            for form in payments_formset:
                row = form.cleaned_data
                if row.get("DELETE") or row.get("amount") is None:
                    continue
                payments.append({"method": row["method"], "amount": row["amount"],
                                 "reference": row.get("reference", "")})
            try:
                sale = checkout_sale(cashier=request.user,
                    customer=details.cleaned_data.get("customer"), items=items, payments=payments,
                    idempotency_key=details.cleaned_data.get("idempotency_key"))
            except ValidationError as exc:
                for error in exc.messages:
                    messages.error(request, error)
            else:
                messages.success(request, f"Sale #{sale.pk} completed.")
                return redirect("sales:receipt", token=sale.receipt_token)
    else:
        details = CheckoutDetailsForm(initial={"idempotency_key": uuid.uuid4()})
        lines = LineFormSet(prefix="items")
        payments_formset = PaymentFormSet(prefix="payments")
    prices = {
        "products": {str(x.pk): str(x.selling_price) for x in Product.objects.filter(active=True)},
        "services": {str(x.pk): str(x.price) for x in Service.objects.filter(active=True)},
    }
    from payments.models import CashSession
    cash_session = CashSession.objects.filter(cashier=request.user, status=CashSession.Status.OPEN).first()
    return render(request, "sales/checkout.html", {
        "details": details, "lines": lines, "payments": payments_formset,
        "prices": prices, "cash_session": cash_session,
    })


@login_required(login_url="login")
def service_queue(request):
    is_manager = request.user.is_superuser or getattr(request.user, "role", None) in {
        User.Role.OWNER, User.Role.MANAGER,
    }
    if not is_manager and getattr(request.user, "role", None) != User.Role.TECHNICIAN:
        raise PermissionDenied

    def pending_lines():
        lines = SaleLine.objects.filter(
            service__isnull=False, service_completed_at__isnull=True,
            sale__status=Sale.Status.COMPLETED, technician__isnull=False,
        ).exclude(
            refund_lines__refund__status__in=(SaleRefund.Status.REQUESTED, SaleRefund.Status.ISSUED)
        ).distinct()
        if not is_manager:
            lines = lines.filter(technician=request.user)
        return lines

    if request.method == "POST":
        line = get_object_or_404(pending_lines(), pk=request.POST.get("sale_line_id"))
        from commissions.services import complete_service_line
        try:
            complete_service_line(
                sale_line=line, technician=line.technician_id, actor=request.user
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"{line.description} marked complete.")
        return redirect("sales:services")

    pending = pending_lines().select_related(
        "sale", "sale__customer", "service", "technician"
    ).distinct()
    return render(request, "sales/service_queue.html", {
        "pending_services": pending[:200], "is_manager": is_manager,
    })


@never_cache
def receipt(request, token):
    sale = get_object_or_404(
        Sale.objects.select_related("customer", "cashier").prefetch_related(
            "lines", "payment_allocations__payment_transaction", "refunds__payout"
        ),
        receipt_token=token,
    )
    response = render(request, "sales/receipt.html", {"sale": sale})
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required(login_url="login")
def balance_payments(request):
    check_role(request.user)
    is_manager = request.user.is_superuser or request.user.role in {User.Role.OWNER, User.Role.MANAGER}
    sales = Sale.objects.filter(status=Sale.Status.COMPLETED)
    if not is_manager:
        sales = sales.filter(cashier=request.user)
    sales = sales.select_related("customer", "cashier").prefetch_related(
        "lines", "payment_allocations__payment_transaction"
    ).order_by("-created_at")[:100]

    if request.method == "POST":
        allowed_sales = Sale.objects.filter(status=Sale.Status.COMPLETED)
        if not is_manager:
            allowed_sales = allowed_sales.filter(cashier=request.user)
        form = BalancePaymentForm(request.POST, sale_queryset=allowed_sales)
        if form.is_valid():
            data = form.cleaned_data
            try:
                record_sale_payment(
                    sale=data["sale"], method=data["method"], amount=data["amount"],
                    reference=data["reference"], actor=request.user,
                    idempotency_key=data["idempotency_key"],
                )
            except ValidationError as exc:
                for error in exc.messages:
                    messages.error(request, error)
            else:
                messages.success(request, f"Payment recorded for {data['sale'].receipt_number}.")
                return redirect("sales:payments")
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)

    sales = list(sales)
    for sale in sales:
        sale.available_for_collection = sale.available_to_collect
        sale.payment_form_key = uuid.uuid4()
    return render(request, "sales/payments.html", {
        "sales": sales, "is_manager": is_manager,
    })


@login_required(login_url="login")
def refunds(request):
    check_role(request.user)
    is_manager = request.user.is_superuser or request.user.role in {User.Role.OWNER, User.Role.MANAGER}
    if request.method == "POST":
        action = request.POST.get("action", "request")
        try:
            if action == "request":
                sale = get_object_or_404(Sale, pk=request.POST.get("sale_id"), status=Sale.Status.COMPLETED)
                items = []
                for line in sale.lines.all():
                    raw_quantity = (request.POST.get(f"quantity_{line.pk}") or "").strip()
                    if raw_quantity in ("", "0"):
                        continue
                    items.append({"sale_line_id": line.pk, "quantity": raw_quantity, "restock": request.POST.get(f"restock_{line.pk}") == "on"})
                request_sale_refund(sale=sale, items=items, method=request.POST.get("method", ""),
                    reference=request.POST.get("reference", ""), reason=request.POST.get("reason", ""), requested_by=request.user)
                messages.success(request, f"Refund request submitted for {sale.receipt_number}.")
            elif action == "issue" and is_manager:
                issue_refund(refund=request.POST.get("refund_id"), approver=request.user, review_reason=request.POST.get("review_reason", ""))
                messages.success(request, "Refund issued and recorded.")
            elif action == "reject" and is_manager:
                reject_refund(refund=request.POST.get("refund_id"), approver=request.user, reason=request.POST.get("review_reason", ""))
                messages.success(request, "Refund request rejected.")
            else:
                raise PermissionDenied
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        return redirect("sales:refunds")
    sales = Sale.objects.filter(status=Sale.Status.COMPLETED).select_related("customer").prefetch_related("lines").order_by("-created_at")[:100]
    refund_list = SaleRefund.objects.select_related("sale", "requested_by", "reviewed_by").prefetch_related("lines__sale_line")
    if not is_manager:
        refund_list = refund_list.filter(requested_by=request.user)
    return render(request, "sales/refunds.html", {"sales": sales, "refunds": refund_list[:100], "is_manager": is_manager})
