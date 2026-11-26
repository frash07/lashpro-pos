from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from datetime import timedelta
import uuid

from django.conf import settings

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from inventory.models import InventoryMovement
from inventory.services import reserved_stock_by_product
from sales.models import Sale, SaleLine

from catalog.models import Product
from .models import StorefrontOrder, StorefrontOrderLine, StorefrontStockReservation


CENT = Decimal("0.01")
ZERO = Decimal("0.00")
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
    source_channel=StorefrontOrder.SourceChannel.STOREFRONT,
    external_order_id="",
):
    """Create an unpaid collection request and reserve its stock atomically; no POS sale is created."""
    cleaned_items = _normalise_items(items)
    key = _normalise_key(idempotency_key)
    customer_name = " ".join(str(customer_name or "").split())
    customer_email = str(customer_email or "").strip().lower()
    customer_phone = str(customer_phone or "").strip()
    notes = str(notes or "").strip()

    external_order_id = str(external_order_id or "").strip()[:160]
    if external_order_id:
        existing_external = StorefrontOrder.objects.filter(
            source_channel=source_channel, external_order_id=external_order_id
        ).first()
        if existing_external:
            return existing_external

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

    # A concurrent retry with the same key may have completed while this
    # request waited for the product-row locks. Recheck before stock validation
    # so the original order wins even when its reservation uses the last unit.
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

    reserved_by_product = reserved_stock_by_product(product.pk for product in locked_products)
    order_lines = []
    total = Decimal("0.00")
    for product_id, quantity in cleaned_items.items():
        product = products[product_id]
        if not product.active:
            raise ValidationError({"items": f"{product.name} is no longer available."})
        reserved = reserved_by_product.get(product.pk, Decimal("0.000"))
        available = product.on_hand - reserved
        if available < Decimal(quantity):
            raise ValidationError({"items": f"Only {available} unreserved unit(s) of {product.name} are currently available."})

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
                source_channel=source_channel,
                external_order_id=external_order_id,
                account=account,
                customer=customer,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                notes=notes,
                total_amount=total.quantize(CENT),
                expires_at=timezone.now() + timedelta(minutes=settings.PUBLIC_ORDER_RESERVATION_MINUTES),
            )
            for line in order_lines:
                line.order = order
            StorefrontOrderLine.objects.bulk_create(order_lines)
            for line in order.lines.select_related("product").all():
                StorefrontStockReservation.objects.create(
                    order_line=line,
                    product=line.product,
                    quantity=Decimal(line.quantity).quantize(Decimal("0.001")),
                )
            transaction.on_commit(lambda order_id=order.pk: _notify_storefront_order(order_id))
    except IntegrityError:
        duplicate = StorefrontOrder.objects.filter(idempotency_key=key).first()
        if duplicate is None and external_order_id:
            duplicate = StorefrontOrder.objects.filter(
                source_channel=source_channel, external_order_id=external_order_id
            ).first()
        if duplicate and duplicate.source_channel == source_channel and _matches_existing_order(
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


def _notify_storefront_order(order_id):
    """Send customer and business order emails after a new request commits."""
    from .notifications import send_storefront_order_notification

    send_storefront_order_notification(order_id)



def _check_order_staff_actor(actor):
    if not getattr(actor, "is_active", False) or not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}
    ):
        raise ValidationError({"actor": "Only an active owner, manager, or cashier can process online orders."})


def _lock_order_products(lines):
    product_ids = sorted({line.product_id for line in lines})
    products = {
        product.pk: product
        for product in Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")
    }
    if len(products) != len(product_ids):
        raise ValidationError({"order": "One or more ordered products no longer exist."})
    return products


def _ensure_order_reservations(*, order, lines, products):
    reserved = reserved_stock_by_product(products.keys())
    for line in lines:
        reservation = StorefrontStockReservation.objects.select_for_update().filter(order_line=line).first()
        if reservation:
            if reservation.status != StorefrontStockReservation.Status.ACTIVE:
                raise ValidationError({"order": f"The reservation for {line.name_snapshot} is no longer active."})
            if reservation.quantity != Decimal(line.quantity).quantize(Decimal("0.001")):
                raise ValidationError({"order": f"The reservation quantity for {line.name_snapshot} does not match the order."})
            continue

        product = products[line.product_id]
        quantity = Decimal(line.quantity).quantize(Decimal("0.001"))
        available = product.on_hand - reserved.get(product.pk, Decimal("0.000"))
        if available < quantity:
            raise ValidationError({"order": f"Only {available} unreserved unit(s) of {product.name} remain; cannot reserve {quantity} for this order."})
        StorefrontStockReservation.objects.create(
            order_line=line, product=product, quantity=quantity
        )
        reserved[product.pk] = reserved.get(product.pk, Decimal("0.000")) + quantity


@transaction.atomic
def create_pos_sale_for_storefront_order(*, order, actor):
    """Create/link the financial POS sale without running a second stock deduction."""
    order_id = order.pk if isinstance(order, StorefrontOrder) else order
    try:
        locked_order = StorefrontOrder.objects.select_for_update().get(pk=order_id)
    except (StorefrontOrder.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"order": "Online order not found."}) from None

    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}
    ):
        raise ValidationError({"actor": "A recorded online-order fulfiller must be an owner, manager, or cashier."})

    order_lines = list(locked_order.lines.order_by("pk"))
    if not order_lines:
        raise ValidationError({"order": "An online order without lines cannot be posted to POS."})

    sale_key = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"lashpro:storefront-order:{locked_order.pk}:{locked_order.idempotency_key}",
    )
    sale = locked_order.sale if locked_order.sale_id else Sale.objects.filter(
        checkout_idempotency_key=sale_key
    ).first()

    if sale is None:
        sale = Sale.objects.create(
            cashier=actor,
            customer=locked_order.customer,
            checkout_idempotency_key=sale_key,
        )
        for order_line in order_lines:
            sale_line = SaleLine(
                sale=sale,
                product_id=order_line.product_id,
                description=order_line.name_snapshot,
                quantity=order_line.quantity,
                unit_price=order_line.unit_price,
                discount=ZERO,
            )
            sale_line.full_clean()
            sale_line.save()
        sale.status = Sale.Status.COMPLETED
        sale.save(update_fields=("status",))

    sale_lines = list(sale.lines.order_by("pk"))
    if sale.status != Sale.Status.COMPLETED or len(sale_lines) != len(order_lines):
        raise ValidationError({"order": "The linked POS sale is incomplete; ask a manager to review it."})
    for sale_line, order_line in zip(sale_lines, order_lines):
        if (
            sale_line.product_id != order_line.product_id
            or sale_line.description != order_line.name_snapshot
            or sale_line.quantity != order_line.quantity
            or sale_line.unit_price != order_line.unit_price
            or sale_line.discount != ZERO
        ):
            raise ValidationError({"order": "The linked POS sale does not match the online order snapshots."})
    if sale.total_amount != locked_order.total_amount:
        raise ValidationError({"order": "The online order total does not match its POS sale; ask a manager to review it."})

    existing_link = StorefrontOrder.objects.filter(sale_id=sale.pk).exclude(pk=locked_order.pk).exists()
    if existing_link:
        raise ValidationError({"order": "This POS sale is already linked to a different online order."})

    if locked_order.sale_id != sale.pk:
        locked_order.sale = sale
        locked_order.save(update_fields=("sale", "updated_at"))
    return sale


@transaction.atomic
def _expire_locked_storefront_order(locked_order, *, now=None):
    """Release one overdue unconfirmed order while its row lock is held."""
    now = now or timezone.now()
    if locked_order.status != StorefrontOrder.Status.PLACED or locked_order.expires_at > now:
        return False
    reservations = list(
        StorefrontStockReservation.objects.select_for_update()
        .filter(order_line__order=locked_order, status=StorefrontStockReservation.Status.ACTIVE)
        .order_by("product_id", "pk")
    )
    for reservation in reservations:
        reservation.status = StorefrontStockReservation.Status.RELEASED
        reservation.released_at = now
        reservation.save(update_fields=("status", "released_at", "updated_at"))
    locked_order.status = StorefrontOrder.Status.EXPIRED
    locked_order.expired_at = now
    locked_order.save(update_fields=("status", "expired_at", "updated_at"))
    return True


@transaction.atomic
def _expire_storefront_order_if_due(order_id, *, now=None):
    now = now or timezone.now()
    order = StorefrontOrder.objects.select_for_update().filter(pk=order_id).first()
    if order is None:
        return False
    return _expire_locked_storefront_order(order, now=now)


def expire_due_storefront_orders(*, limit=500):
    """Materialise expired order states and release their stock holds."""
    now = timezone.now()
    order_ids = list(
        StorefrontOrder.objects.filter(
            status=StorefrontOrder.Status.PLACED,
            expires_at__lte=now,
        ).order_by("expires_at", "pk").values_list("pk", flat=True)[:limit]
    )
    return sum(1 for order_id in order_ids if _expire_storefront_order_if_due(order_id, now=now))


@transaction.atomic
def transition_storefront_order(*, order, target_status, actor):
    """Move an online order through staff workflow, consume stock and post its POS sale."""
    _check_order_staff_actor(actor)
    order_id = order.pk if isinstance(order, StorefrontOrder) else order
    try:
        locked_order = StorefrontOrder.objects.select_for_update().get(pk=order_id)
    except (StorefrontOrder.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"order": "Online order not found."}) from None

    try:
        target_status = StorefrontOrder.Status(target_status)
    except ValueError:
        raise ValidationError({"status": "Choose a valid online order status."}) from None

    # A staff confirmation arriving after the public hold deadline cannot
    # revive the reservation; release it and expose the EXPIRED state instead.
    if _expire_locked_storefront_order(locked_order):
        return locked_order

    allowed = {
        StorefrontOrder.Status.PLACED: {StorefrontOrder.Status.CONFIRMED, StorefrontOrder.Status.CANCELLED},
        StorefrontOrder.Status.CONFIRMED: {StorefrontOrder.Status.READY, StorefrontOrder.Status.CANCELLED},
        StorefrontOrder.Status.READY: {StorefrontOrder.Status.FULFILLED, StorefrontOrder.Status.CANCELLED},
    }
    if target_status not in allowed.get(locked_order.status, set()):
        raise ValidationError({"status": f"An order in {locked_order.get_status_display()} cannot move to {target_status.label}."})

    lines = list(locked_order.lines.select_related("product").order_by("product_id", "pk"))
    products = _lock_order_products(lines)
    before_status = locked_order.status

    if target_status in {
        StorefrontOrder.Status.CONFIRMED,
        StorefrontOrder.Status.READY,
        StorefrontOrder.Status.FULFILLED,
    }:
        _ensure_order_reservations(order=locked_order, lines=lines, products=products)

    if target_status == StorefrontOrder.Status.CANCELLED:
        now = timezone.now()
        reservations = list(
            StorefrontStockReservation.objects.select_for_update()
            .filter(order_line__order=locked_order, status=StorefrontStockReservation.Status.ACTIVE)
            .order_by("product_id", "pk")
        )
        for reservation in reservations:
            reservation.status = StorefrontStockReservation.Status.RELEASED
            reservation.released_at = now
            reservation.save(update_fields=("status", "released_at", "updated_at"))

    elif target_status == StorefrontOrder.Status.FULFILLED:
        now = timezone.now()
        for line in lines:
            product = products[line.product_id]
            reservation = StorefrontStockReservation.objects.select_for_update().get(order_line=line)
            quantity = Decimal(line.quantity).quantize(Decimal("0.001"))
            if reservation.status != StorefrontStockReservation.Status.ACTIVE:
                raise ValidationError({"order": f"The stock reservation for {line.name_snapshot} is not active."})
            if reservation.quantity != quantity:
                raise ValidationError({"order": f"The reserved quantity for {line.name_snapshot} does not match the order."})
            if product.on_hand < quantity:
                raise ValidationError({"order": f"Physical stock for {product.name} is below the reserved order quantity. Reconcile inventory before fulfilment."})

            before_stock = product.on_hand
            product.on_hand = before_stock - quantity
            product.save(update_fields=("on_hand",))
            movement = InventoryMovement.objects.create(
                product=product,
                movement_type=InventoryMovement.Type.ONLINE_ORDER,
                quantity_delta=-quantity,
                storefront_order_line=line,
                unit_cost=product.cost_price,
                actor=actor,
                reason=f"Fulfilled online order {locked_order.reference}.",
            )
            reservation.status = StorefrontStockReservation.Status.CONSUMED
            reservation.consumed_at = now
            reservation.save(update_fields=("status", "consumed_at", "updated_at"))
            record_audit_event(
                event_type=AuditEvent.EventType.SALE_STOCK_DEDUCTION,
                object_type="inventory_movement",
                object_id=movement.pk,
                actor=actor,
                reason=movement.reason,
                before_state={"on_hand": str(before_stock)},
                after_state={"on_hand": str(product.on_hand)},
                metadata={
                    "product_id": product.pk,
                    "online_order_id": locked_order.pk,
                    "online_order_reference": locked_order.reference,
                    "order_line_id": line.pk,
                    "reservation_id": reservation.pk,
                },
            )

    pos_sale = None
    if target_status == StorefrontOrder.Status.FULFILLED:
        pos_sale = create_pos_sale_for_storefront_order(order=locked_order, actor=actor)
        locked_order.sale = pos_sale

    locked_order.status = target_status
    locked_order.save(update_fields=("status", "updated_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="storefront_order",
        object_id=locked_order.pk,
        actor=actor,
        reason=(
            f"Online order status changed from {before_status} to {target_status}; "
            f"POS sale {pos_sale.receipt_number} created."
            if pos_sale else
            f"Online order status changed from {before_status} to {target_status}."
        ),
        before_state={"status": before_status},
        after_state={
            "status": target_status,
            "pos_sale_id": pos_sale.pk if pos_sale else None,
            "pos_receipt_number": pos_sale.receipt_number if pos_sale else None,
        },
        metadata={
            "reference": locked_order.reference,
            "pos_sale_id": pos_sale.pk if pos_sale else None,
            "pos_receipt_number": pos_sale.receipt_number if pos_sale else None,
        },
    )
    return locked_order
