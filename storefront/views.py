import secrets
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Product, Service
from core.public_throttle import public_rate_limit
from customers.models import Customer
from inventory.services import available_stock_by_product, available_stock_for_product
from payments.mpesa import initiate_stk_push, normalize_mpesa_phone, storefront_stk_available, _validate_amount
from .forms import CustomerLoginForm, CustomerRegistrationForm, StorefrontCheckoutForm
from .models import StorefrontOrder, StorefrontProfile
from .services import create_storefront_order, expire_due_storefront_orders


CART_SESSION_KEY = "storefront_cart"
CHECKOUT_KEY_SESSION_KEY = "storefront_checkout_key"


def _profile_for(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.storefront_profile
    except StorefrontProfile.DoesNotExist:
        return None


def _cart_count(request):
    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        return 0
    count = 0
    for raw_quantity in cart.values():
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            continue
        count += max(quantity, 0)
    return count


def _base_context(request):
    return {
        "pos_url": settings.POS_BASE_URL,
        "cart_count": _cart_count(request),
        "customer_account": _profile_for(request.user),
    }


def privacy_policy(request):
    return render(request, "storefront/privacy.html", _base_context(request))


def terms_of_service(request):
    return render(request, "storefront/terms.html", _base_context(request))


def returns_policy(request):
    return render(request, "storefront/returns.html", _base_context(request))


def _cart_details(request):
    expire_due_storefront_orders(limit=100)
    raw_cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(raw_cart, dict):
        raw_cart = {}

    cleaned = {}
    for raw_product_id, raw_quantity in raw_cart.items():
        try:
            product_id = int(raw_product_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError, OverflowError):
            continue
        if product_id > 0 and 1 <= quantity <= 99:
            cleaned[str(product_id)] = quantity

    products = list(Product.objects.filter(pk__in=[int(key) for key in cleaned], active=True).order_by("name"))
    available_by_id = available_stock_by_product(products)
    items = []
    total = 0
    for product in products:
        product.available_stock = available_by_id[product.pk]
        quantity = cleaned[str(product.pk)]
        available = product.available_stock >= quantity
        line_total = product.selling_price * quantity
        total += line_total
        items.append({
            "product": product,
            "quantity": quantity,
            "line_total": line_total,
            "available": available,
        })

    # Remove deleted, inactive, malformed, or unsupported session entries.
    valid_ids = {str(item["product"].pk) for item in items}
    cleaned = {key: value for key, value in cleaned.items() if key in valid_ids}
    if cleaned != raw_cart:
        request.session[CART_SESSION_KEY] = cleaned
        request.session.modified = True

    return items, total


def home(request):
    """Render the public catalogue, or send the POS hostname to staff checkout."""
    hostname = request.get_host().split(":", 1)[0].lower()
    pos_hosts = {host.lower() for host in getattr(settings, "POS_HOSTS", [])}
    if hostname in pos_hosts:
        return redirect("sales:checkout")

    query = (request.GET.get("q") or "").strip()[:80]
    kind = (request.GET.get("kind") or "all").strip().lower()
    if kind not in {"all", "products", "services"}:
        kind = "all"

    products = Product.objects.filter(active=True).order_by("name")
    services = Service.objects.filter(active=True).order_by("name")
    active_service_count = Service.objects.filter(active=True).count()
    if query:
        # Match every search word against the product name/SKU or service name/type.
        # Repeated filters make multi-word searches work regardless of word order.
        for term in query.split():
            products = products.filter(Q(name__icontains=term) | Q(sku__icontains=term))
            services = services.filter(Q(name__icontains=term) | Q(kind__icontains=term))
    if kind == "products":
        services = Service.objects.none()
    elif kind == "services":
        products = Product.objects.none()

    products = list(products)
    available_by_id = available_stock_by_product(products)
    for product in products:
        product.available_stock = available_by_id[product.pk]

    context = _base_context(request)
    context.update({
        "products": products,
        "services": services,
        "query": query,
        "kind": kind,
        "product_count": len(products),
        "service_count": services.count(),
        "active_service_count": active_service_count,
    })
    return render(request, "storefront/home.html", context)


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, active=True)
    available_quantity = max(int(available_stock_for_product(product)), 0)
    if available_quantity < 1:
        messages.error(request, "This product is currently out of stock.")
        return redirect("storefront:home")

    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}
    current = int(cart.get(str(product.pk), 0) or 0)
    if current + 1 > min(available_quantity, 99):
        messages.warning(request, f"Only {available_quantity} unit(s) of {product.name} are currently available.")
    else:
        cart[str(product.pk)] = current + 1
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
        messages.success(request, f"{product.name} added to your bag.")
    return redirect("storefront:cart")


@require_POST
def cart_update(request, product_id):
    product = get_object_or_404(Product, pk=product_id, active=True)
    try:
        quantity = int(request.POST.get("quantity", ""))
    except (TypeError, ValueError):
        messages.error(request, "Enter a valid whole-number quantity.")
        return redirect("storefront:cart")

    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}
    if quantity <= 0:
        cart.pop(str(product.pk), None)
    else:
        available_quantity = max(int(available_stock_for_product(product)), 0)
        if quantity > 99 or quantity > available_quantity:
            messages.error(request, f"Only {available_quantity} unreserved unit(s) of {product.name} are currently available.")
            return redirect("storefront:cart")
        cart[str(product.pk)] = quantity
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True
    return redirect("storefront:cart")


@require_POST
def cart_remove(request, product_id):
    cart = request.session.get(CART_SESSION_KEY, {})
    if isinstance(cart, dict):
        cart.pop(str(product_id), None)
        request.session[CART_SESSION_KEY] = cart
        request.session.modified = True
    return redirect("storefront:cart")


def cart(request):
    items, total = _cart_details(request)
    context = _base_context(request)
    context.update({"items": items, "total": total, "has_unavailable_items": any(not item["available"] for item in items)})
    return render(request, "storefront/cart.html", context)


@public_rate_limit("storefront-checkout", limits={"GET": (60, 60), "POST": (5, 900)})
@never_cache
def checkout(request):
    items, total = _cart_details(request)
    if not items:
        messages.info(request, "Your bag is empty. Add a product before checkout.")
        return redirect("storefront:cart")
    if any(not item["available"] for item in items):
        messages.error(request, "One or more quantities are no longer available. Update your bag before checkout.")
        return redirect("storefront:cart")

    profile = _profile_for(request.user)
    checkout_key = request.session.get(CHECKOUT_KEY_SESSION_KEY)
    if not checkout_key:
        checkout_key = str(uuid.uuid4())
        request.session[CHECKOUT_KEY_SESSION_KEY] = checkout_key

    initial = {"idempotency_key": checkout_key}
    if profile:
        initial.update({
            "full_name": profile.customer.name,
            "email": profile.email,
            "phone": profile.customer.phone,
        })

    mpesa_available = storefront_stk_available()
    if request.method == "POST":
        form = StorefrontCheckoutForm(request.POST)
        method = request.POST.get("payment_method", StorefrontOrder.PaymentMethod.PAY_AT_STUDIO)
        if form.is_valid():
            if method == StorefrontOrder.PaymentMethod.MPESA:
                if not mpesa_available:
                    form.add_error(None, "Online M-Pesa is not currently available.")
                else:
                    try:
                        normalize_mpesa_phone(form.cleaned_data["phone"])
                        _validate_amount(total)
                    except ValidationError as exc:
                        form.add_error(None, " ".join(exc.messages))
        if not form.errors:
            try:
                order = create_storefront_order(
                    items={str(item["product"].pk): item["quantity"] for item in items},
                    customer_name=form.cleaned_data["full_name"],
                    customer_email=form.cleaned_data["email"],
                    customer_phone=form.cleaned_data["phone"],
                    notes=form.cleaned_data["notes"],
                    account=profile.user if profile else None,
                    customer=profile.customer if profile else None,
                    idempotency_key=form.cleaned_data["idempotency_key"],
                    payment_method=method,
                )
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                request.session.pop(CART_SESSION_KEY, None)
                request.session.pop(CHECKOUT_KEY_SESSION_KEY, None)
                if order.payment_method == StorefrontOrder.PaymentMethod.MPESA:
                    _send_order_prompt(request, order)
                else:
                    messages.success(request, "Your order request has been received.")
                return redirect("storefront:order-detail", token=order.access_token)
        else:
            if not form.cleaned_data.get("idempotency_key"):
                form.fields["idempotency_key"].initial = checkout_key
    else:
        form = StorefrontCheckoutForm(initial=initial)

    context = _base_context(request)
    context.update({"items": items, "total": total, "form": form, "is_guest_checkout": profile is None, "mpesa_available": mpesa_available})
    return render(request, "storefront/checkout.html", context)


def _send_order_prompt(request, order, retry_id=None):
    if not storefront_stk_available():
        messages.warning(request, "Online M-Pesa is currently unavailable. Contact the studio.")
        return
    token = secrets.token_urlsafe(48)
    callback_url = settings.POS_BASE_URL.rstrip("/") + reverse(
        "payments:mpesa-stk-callback", kwargs={"token": token}
    )
    try:
        initiate_stk_push(
            storefront_order=order, amount=order.total_amount,
            phone=order.customer_phone, callback_url=callback_url,
            callback_token=token, retry_id=retry_id,
        )
    except ValidationError:
        # Provider details and credentials are not customer-facing.
        messages.warning(request, "Check the payment status below before trying again.")


@public_rate_limit("storefront-stk-retry", limits={"POST": (3, 900)})
@require_POST
@never_cache
def retry_order_payment(request, token):
    order = get_object_or_404(StorefrontOrder, access_token=token)
    retry_id = request.POST.get("attempt")
    if retry_id:
        _send_order_prompt(request, order, retry_id=retry_id)
    return redirect("storefront:order-detail", token=order.access_token)


@never_cache
@public_rate_limit("storefront-order-detail", limits={"GET": (120, 60)})
def order_detail(request, token):
    expire_due_storefront_orders(limit=100)
    order = get_object_or_404(
        StorefrontOrder.objects.prefetch_related("lines"),
        access_token=token,
    )
    context = _base_context(request)
    context["order"] = order
    if order.payment_method == StorefrontOrder.PaymentMethod.MPESA:
        push = order.mpesa_payment
        context["mpesa_payment"] = push
        context["can_retry_mpesa"] = (
            order.status == StorefrontOrder.Status.PLACED
            and order.expires_at > timezone.now()
            and (not push or push.status == "FAILED")
            and storefront_stk_available()
        )
    context["reservation_minutes"] = settings.PUBLIC_ORDER_RESERVATION_MINUTES
    return render(request, "storefront/order_detail.html", context)


@never_cache
@public_rate_limit("storefront-register", limits={"POST": (3, 3600)})
def register(request):
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            full_name = form.cleaned_data["full_name"]
            parts = full_name.split(maxsplit=1)
            email = form.cleaned_data["email"]
            try:
                with transaction.atomic():
                    username = "web-" + uuid.uuid4().hex
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        first_name=parts[0],
                        last_name=parts[1] if len(parts) > 1 else "",
                        password=form.cleaned_data["password1"],
                        role=User.Role.CUSTOMER,
                        is_staff=False,
                        is_superuser=False,
                    )
                    customer = Customer.objects.create(
                        name=full_name,
                        phone=form.cleaned_data["phone"],
                    )
                    StorefrontProfile.objects.create(
                        user=user,
                        customer=customer,
                        email=email,
                    )
            except IntegrityError:
                form.add_error("email", "An account already uses this email. Sign in instead.")
            else:
                messages.success(request, "Your LashPro customer account has been created. Sign in to continue.")
                return redirect("storefront:login")
    else:
        form = CustomerRegistrationForm()

    context = _base_context(request)
    context["form"] = form
    return render(request, "storefront/register.html", context)


@never_cache
def customer_login(request):
    if _profile_for(request.user):
        return redirect("storefront:account-orders")

    if request.method == "POST":
        form = CustomerLoginForm(request.POST)
        if form.is_valid():
            profile = StorefrontProfile.objects.select_related("user").filter(
                email__iexact=form.cleaned_data["email"]
            ).first()
            user = None
            if profile:
                user = authenticate(
                    request,
                    username=profile.user.username,
                    password=form.cleaned_data["password"],
                )
            if user and user.role == User.Role.CUSTOMER and _profile_for(user):
                auth_login(request, user)
                return redirect("storefront:account-orders")
            form.add_error(None, "Email or password was not recognised.")
    else:
        form = CustomerLoginForm()

    context = _base_context(request)
    context["form"] = form
    return render(request, "storefront/login.html", context)


@require_POST
def customer_logout(request):
    auth_logout(request)
    messages.success(request, "You have signed out.")
    return redirect("storefront:home")


@login_required(login_url="storefront:login")
@never_cache
def account_orders(request):
    expire_due_storefront_orders(limit=500)
    profile = _profile_for(request.user)
    if not profile or request.user.role != User.Role.CUSTOMER:
        raise PermissionDenied
    orders = StorefrontOrder.objects.filter(account=request.user).prefetch_related("lines")
    context = _base_context(request)
    context["orders"] = orders
    return render(request, "storefront/account_orders.html", context)
