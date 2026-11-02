import json
import uuid
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from accounts.models import User
from catalog.models import Product, Service
from customers.models import Customer
from .forms import BalancePaymentForm, CheckoutDetailsForm, LineFormSet, PaymentFormSet
from .models import Sale, SaleLine, SaleRefund
from .services import checkout_sale, issue_refund, record_sale_payment, reject_refund, request_sale_refund

ALLOWED_ROLES = {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}


def check_role(user):
    if not (user.is_superuser or getattr(user, "role", None) in ALLOWED_ROLES):
        raise PermissionDenied


@login_required(login_url="login")
def customer_search(request):
    """Authenticated autocomplete for checkout: search customers by name or phone."""
    check_role(request.user)
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        from django.db.models import Q
        qs = (
            Customer.objects.filter(Q(name__icontains=q) | Q(phone__icontains=q))
            .order_by("name")[:12]
        )
        results = [
            {"id": c.pk, "name": c.name, "phone": c.phone or ""}
            for c in qs
        ]
    return JsonResponse(results, safe=False)


def _build_admin_suite_context(user):
    """Role gate and server-side summary for the Admin Suite panel on the checkout page."""
    from payments.models import PaymentTransaction

    is_manager = user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}
    pending_count = 0
    if is_manager:
        # Count every UNVERIFIED M-Pesa transaction, not just the recent rows shown in a table.
        pending_count = PaymentTransaction.objects.filter(
            method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED,
        ).count()
    return {
        "is_manager": is_manager,
        "pending_reconciliation_count": pending_count,
    }


def _build_checkout_initial_cart(lines):
    """Rehydrate the cart from submitted formset data when checkout validation fails."""
    cart = []
    for form in lines.forms:
        prefix = form.prefix
        if (form.data or {}).get(f"{prefix}-DELETE") == "on":
            continue

        product_id = (form.data.get(f"{prefix}-product") or "").strip()
        service_id = (form.data.get(f"{prefix}-service") or "").strip()
        if not product_id and not service_id:
            continue

        try:
            quantity = int(form.data.get(f"{prefix}-quantity") or "1")
        except (TypeError, ValueError):
            quantity = 1
        if quantity <= 0:
            continue

        discount = form.data.get(f"{prefix}-discount") or "0.00"
        discount_reason = form.data.get(f"{prefix}-discount_reason") or ""

        item = {
            "qty": quantity,
            "discount": discount,
            "discount_reason": discount_reason,
        }
        if product_id:
            product = Product.objects.filter(pk=product_id, active=True).first()
            if not product:
                continue
            item.update({
                "id": f"product-{product.pk}",
                "type": "product",
                "name": product.name,
                "price": float(product.selling_price),
                "product_id": product.pk,
            })
        else:
            service = Service.objects.filter(pk=service_id, active=True).first()
            if not service:
                continue
            item.update({
                "id": f"service-{service.pk}",
                "type": "service",
                "name": service.name,
                "price": float(service.price),
                "service_id": service.pk,
            })

        technician_id = (form.data.get(f"{prefix}-technician") or "").strip()
        if technician_id:
            try:
                item["technician_id"] = int(technician_id)
            except (TypeError, ValueError):
                pass
        cart.append(item)
    return cart


def _build_checkout_initial_payments(payments):
    """Rehydrate submitted payment rows so validation failures keep the same payment state."""
    rows = []
    for form in payments.forms:
        prefix = form.prefix
        if (form.data or {}).get(f"{prefix}-DELETE") == "on":
            continue

        method = (form.data.get(f"{prefix}-method") or "").strip()
        amount = form.data.get(f"{prefix}-amount") or ""
        reference = (form.data.get(f"{prefix}-reference") or "").strip()
        if method or amount or reference:
            rows.append({
                "method": method,
                "amount": amount,
                "reference": reference,
            })
    return rows


@login_required(login_url="login")
def checkout(request):
    check_role(request.user)
    if request.method == "POST":
        details = CheckoutDetailsForm(request.POST)
        lines = LineFormSet(request.POST, prefix="items")
        payments_formset = PaymentFormSet(request.POST, prefix="payments")
        initial_cart = _build_checkout_initial_cart(lines)
        initial_payments = _build_checkout_initial_payments(payments_formset)
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
        initial_cart = []
        initial_payments = []
        details = CheckoutDetailsForm(initial={"idempotency_key": uuid.uuid4()})
        lines = LineFormSet(prefix="items")
        payments_formset = PaymentFormSet(prefix="payments")

    products = list(Product.objects.filter(active=True).order_by("name"))
    sample_descriptions = {
        "lashpro retention bond (10ml)": "Maximum Strength 1-Sec Lash Glue",
        "silk cashmere trays 0.07": "Mixed Length C/D Curl Lash Trays",
        "precision tweezers set": "Japanese Steel Isolation & Volume Tweezers",
        "aftercare cleansing foam": "Oil-Free Lash Shampoo & Brush Kit",
    }
    for product in products:
        product.pos_description = sample_descriptions.get(product.name.strip().casefold(), "")
    services = list(Service.objects.filter(active=True).order_by("name"))
    prices = {
        "products": {str(x.pk): str(x.selling_price) for x in products},
        "services": {str(x.pk): str(x.price) for x in services},
    }
    catalog_items = []
    for product in products:
        catalog_items.append({
            "id": f"product-{product.pk}",
            "name": product.name,
            "price": float(product.selling_price),
            "type": "product",
            "desc": product.pos_description or product.name,
            "icon": "package",
            "stock": float(product.on_hand),
            "sku": product.sku,
        })
    for service in services:
        catalog_items.append({
            "id": f"service-{service.pk}",
            "name": service.name,
            "price": float(service.price),
            "type": "service",
            "desc": f"{service.duration_minutes} minute session",
            "icon": "sparkles",
            "duration_minutes": service.duration_minutes,
            "commission_eligible": service.commission_eligible,
            "commission_rate": float(service.commission_rate),
        })
    from payments.models import CashSession
    cash_session = CashSession.objects.filter(cashier=request.user, status=CashSession.Status.OPEN).first()
    technicians = list(User.objects.filter(
        role=User.Role.TECHNICIAN, is_active=True
    ).order_by("first_name", "username"))
    default_technician_id = request.user.pk if getattr(request.user, "role", None) == User.Role.TECHNICIAN else None
    technician_payload = [
        {"id": technician.pk, "name": technician.get_full_name() or technician.username}
        for technician in technicians
    ]
    return render(request, "sales/checkout.html", {
        "admin_suite": _build_admin_suite_context(request.user),
        "details": details, "lines": lines, "payments": payments_formset,
        "prices": prices, "products": products, "services": services,
        "catalog_items": catalog_items, "catalog_data_json": json.dumps(catalog_items),
        "initial_cart": initial_cart,
        "initial_payments": initial_payments,
        "cash_session": cash_session,
        "can_discount": request.user.is_superuser or request.user.role in {
            User.Role.OWNER, User.Role.MANAGER,
        },
        "technicians": technicians, "default_technician_id": default_technician_id,
        "technicians_json": json.dumps(technician_payload),
    })
