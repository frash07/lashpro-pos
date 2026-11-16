from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import Product
from .models import StorefrontOrder, StorefrontOrderLine


CENT = Decimal("0.01")
MAX_CART_LINES = 25
MAX_QUANTITY = 99


def _normalise_items(items):
    if not isinstance(items, Mapping) or not items:
        raise ValidationError({"items": "Add at least one product before checkout."})
    if len(items) > MAX_CART_LINES:
        raise ValidationError({"items": f"A cart can contain at most {MAX_CART_LINES} different products."})

    cleaned = {}
    for raw_product_id, raw_quantity in items.items():
        try:
            product_id = int(raw_product_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError, OverflowError):
            raise ValidationError({"items": "The cart contains an invalid product or quantity."}) from None
        if product_id < 1 or quantity < 1 or quantity > MAX_QUANTITY:
            raise ValidationError({"items": "Product quantities must be between 1 and 99."})
        if str(product_id) in cleaned:
            raise ValidationError({"items": "The cart contains a duplicate product."})
        cleaned[str(product_id)] = quantity
    return cleaned


def _normalise_key(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({"idempotency_key": "Refresh checkout and try again."}) from None


def _matches_existing_order(order, *, items, customer_name, customer_email, customer_phone, notes, account, customer):
    existing_items = {
        str(line.product_id): line.quantity
        for line in order.lines.all()
    }
    return (
        existing_items == items
        and order.customer_name == customer_name
        and order.customer_email == customer_email
        and order.customer_phone == customer_phone
        and order.notes == notes
        and order.account_id == getattr(account, "pk", None)
        and order.customer_id == getattr(customer, "pk", None)
    )


@transaction.atomic
def create_storefront_order(
    *,
    items,
    customer_name,
    customer_email,
    customer_phone,
    notes="",
    account=None,
    customer=None,
    idempotency_key,
):
    """Create an unpaid, unreserved collection request; never creates a POS sale."""
    cleaned_items = _normalise_items(items)
    key = _normalise_key(idempotency_key)
    customer_name = " ".join(str(customer_name or "").split())
    customer_email = str(customer_email or "").strip().lower()
    customer_phone = str(customer_phone or "").strip()
    notes = str(notes or "").strip()

    existing = StorefrontOrder.objects.filter(idempotency_key=key).first()
    if existing:
        if _matches_existing_order(
            existing,
            items=cleaned_items,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            notes=notes,
            account=account,
            customer=customer,
        ):
            return existing
        raise ValidationError({"idempotency_key": "This checkout key was already used. Start a fresh checkout."})

    product_ids = [int(product_id) for product_id in cleaned_items]
    locked_products = list(
        Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")
    )
    products = {str(product.pk): product for product in locked_products}
    if len(products) != len(cleaned_items):
        raise ValidationError({"items": "One or more products are no longer available."})

    order_lines = []
    total = Decimal("0.00")
    for product_id, quantity in cleaned_items.items():
        product = products[product_id]
        if not product.active:
            raise ValidationError({"items": f"{product.name} is no longer available."})
        if product.on_hand < Decimal(quantity):
            raise ValidationError({"items": f"Only {product.on_hand} unit(s) of {product.name} are currently available."})

        try:
            unit_price = Decimal(product.selling_price).quantize(CENT)
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError({"items": f"The price for {product.name} is unavailable. Contact the studio."}) from None
        line_total = (unit_price * quantity).quantize(CENT)
        total += line_total
        order_lines.append(
            StorefrontOrderLine(
                product=product,
                sku_snapshot=product.sku,
                name_snapshot=product.name,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    try:
        with transaction.atomic():
            order = StorefrontOrder.objects.create(
                idempotency_key=key,
                account=account,
                customer=customer,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                notes=notes,
                total_amount=total.quantize(CENT),
            )
            for line in order_lines:
                line.order = order
            StorefrontOrderLine.objects.bulk_create(order_lines)
    except IntegrityError:
        duplicate = StorefrontOrder.objects.filter(idempotency_key=key).first()
        if duplicate and _matches_existing_order(
            duplicate,
            items=cleaned_items,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            notes=notes,
            account=account,
            customer=customer,
        ):
            return duplicate
        raise ValidationError({"idempotency_key": "This checkout was already submitted. Review your order status."}) from None

    return order
