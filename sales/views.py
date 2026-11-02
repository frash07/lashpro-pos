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
        pending_count = PaymentTransaction.objects.filter(
            method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED,
        ).count()
    return {
        "is_manager": is_manager,
        "pending_reconciliation_count": pending_count,
    }
