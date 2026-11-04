from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from .forms import StockReceiptForm, StockReceiptLineFormSet
from .models import StockReceipt
from .services import receive_supplier_stock


def _can_manage_inventory(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER})
    )


@login_required(login_url="login")
def receive_stock_view(request):
    if not _can_manage_inventory(request.user):
        raise PermissionDenied

    form = StockReceiptForm(request.POST or None)
    line_formset = StockReceiptLineFormSet(request.POST or None, prefix="lines")
    if request.method == "POST" and form.is_valid() and line_formset.is_valid():
        lines = [
            {
                "product": item["product"],
                "quantity": item["quantity"],
                "unit_cost": item["unit_cost"],
            }
            for item in line_formset.cleaned_data
            if item and not item.get("DELETE", False)
        ]
        try:
            receipt, created = receive_supplier_stock(
                supplier=form.cleaned_data["supplier"],
                reference_type=form.cleaned_data["reference_type"],
                supplier_reference=form.cleaned_data["supplier_reference"],
                delivery_note_number=form.cleaned_data["delivery_note_number"],
                received_date=form.cleaned_data["received_date"],
                notes=form.cleaned_data["notes"],
                lines=lines,
                actor=request.user,
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ValidationError as exc:
            for error in exc.messages:
                form.add_error(None, error)
        else:
            if created:
                messages.success(
                    request,
                    f"Supplier receipt #{receipt.pk} recorded: {receipt.supplier} · "
                    f"{receipt.lines.count()} product line(s) · KSh {receipt.total_cost:,.2f}.",
                )
            else:
                messages.info(
                    request,
                    f"Receipt #{receipt.pk} was already recorded. Stock was not changed again.",
                )
            return redirect("inventory:receipt_detail", receipt_id=receipt.pk)

    return render(request, "inventory/receive.html", {
        "form": form,
        "line_formset": line_formset,
    })


@login_required(login_url="login")
def stock_receipts_view(request):
    if not _can_manage_inventory(request.user):
        raise PermissionDenied
    receipts = (
        StockReceipt.objects
        .select_related("supplier", "received_by")
        .prefetch_related("lines__product")
        .order_by("-received_date", "-created_at")[:100]
    )
    return render(request, "inventory/receipts.html", {"receipts": receipts})


@login_required(login_url="login")
def stock_receipt_detail_view(request, receipt_id):
    if not _can_manage_inventory(request.user):
        raise PermissionDenied
    receipt = get_object_or_404(
        StockReceipt.objects
        .select_related("supplier", "received_by")
        .prefetch_related("lines__product", "lines__movement"),
        pk=receipt_id,
    )
    return render(request, "inventory/receipt_detail.html", {"receipt": receipt})
