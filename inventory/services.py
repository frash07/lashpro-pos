from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from catalog.models import Product
from .models import InventoryMovement, StockAdjustmentRequest

UNIT = Decimal("0.001")


def _quantity(value):
    try:
        quantity = Decimal(str(value))
        rounded = quantity.quantize(UNIT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity_delta": "Enter stock to three decimal places or fewer."}) from None
    if not quantity.is_finite() or quantity != rounded or not quantity:
        raise ValidationError({"quantity_delta": "Adjustment must be a non-zero stock quantity."})
    return rounded


@transaction.atomic
def deduct_product_for_sale_line(*, sale_line, actor):
    if not sale_line.product_id:
        return None
    product = Product.objects.select_for_update().get(pk=sale_line.product_id)
    existing = InventoryMovement.objects.filter(sale_line=sale_line, movement_type="SALE").first()
    if existing:
        return existing
    quantity = Decimal(sale_line.quantity).quantize(UNIT)
    if product.on_hand < quantity:
        raise ValidationError({"items": f"Not enough stock for {product.name}. Available: {product.on_hand}; requested: {quantity}."})
    before = product.on_hand
    product.on_hand = before - quantity
    product.save(update_fields=("on_hand",))
    movement = InventoryMovement.objects.create(
        product=product, movement_type=InventoryMovement.Type.SALE,
        quantity_delta=-quantity, sale_line=sale_line, actor=actor,
        reason=f"Sold on Sale #{sale_line.sale_id}",
    )
    record_audit_event(
        event_type=AuditEvent.EventType.SALE_STOCK_DEDUCTION,
        object_type="inventory_movement", object_id=movement.pk, actor=actor,
        reason=movement.reason, before_state={"on_hand": str(before)},
        after_state={"on_hand": str(product.on_hand)},
        metadata={"product_id": product.pk, "sale_id": sale_line.sale_id, "sale_line_id": sale_line.pk},
    )
    return movement


@transaction.atomic
def request_stock_adjustment(*, product, quantity_delta, reason, requested_by):
    product_id = product.pk if isinstance(product, Product) else product
    delta, reason = _quantity(quantity_delta), (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Explain why this adjustment is requested."})
    try:
        product = Product.objects.get(pk=product_id)
    except (Product.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"product": "Choose a valid product."}) from None
    request = StockAdjustmentRequest(product=product, quantity_delta=delta, reason=reason, requested_by=requested_by)
    request.full_clean()
    request.save()
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="stock_adjustment",
        object_id=request.pk, actor=requested_by, reason=reason,
        after_state={"status": request.status, "quantity_delta": str(delta)},
        metadata={"product_id": product.pk},
    )
    return request


@transaction.atomic
def review_stock_adjustment(*, adjustment, approver, approve, reason=""):
    request_id = adjustment.pk if isinstance(adjustment, StockAdjustmentRequest) else adjustment
    try:
        request = StockAdjustmentRequest.objects.select_for_update().get(pk=request_id)
    except (StockAdjustmentRequest.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"adjustment": "Stock adjustment request not found."}) from None
    if request.status != StockAdjustmentRequest.Status.PENDING:
        raise ValidationError({"adjustment": "This request has already been reviewed."})
    if not (approver.is_superuser or getattr(approver, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise ValidationError({"approver": "Only an owner or manager can review adjustments."})
    if approver.pk == request.requested_by_id:
        raise ValidationError({"approver": "A different owner or manager must approve this adjustment."})
    review_reason = (reason or "").strip()
    if not approve:
        request.status, request.reviewed_by = StockAdjustmentRequest.Status.REJECTED, approver
        request.review_reason, request.reviewed_at = review_reason, timezone.now()
        request.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))
        record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL, object_type="stock_adjustment",
            object_id=request.pk, actor=approver, approver=approver,
            reason=review_reason or request.reason,
            before_state={"status": StockAdjustmentRequest.Status.PENDING},
            after_state={"status": StockAdjustmentRequest.Status.REJECTED},
            metadata={"requested_by_id": request.requested_by_id, "product_id": request.product_id},
        )
        return request

    product = Product.objects.select_for_update().get(pk=request.product_id)
    before, after = product.on_hand, product.on_hand + request.quantity_delta
    if after < 0:
        raise ValidationError({"quantity_delta": f"Adjustment would make stock negative (current: {before})."})
    product.on_hand = after
    product.save(update_fields=("on_hand",))
    request.status, request.reviewed_by = StockAdjustmentRequest.Status.APPROVED, approver
    request.review_reason, request.reviewed_at = review_reason, timezone.now()
    request.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))
    movement = InventoryMovement.objects.create(
        product=product, movement_type=InventoryMovement.Type.ADJUSTMENT,
        quantity_delta=request.quantity_delta, source_adjustment=request,
        actor=approver, reason=request.reason,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.STOCK_ADJUSTMENT, object_type="inventory_movement",
        object_id=movement.pk, actor=request.requested_by, approver=approver,
        reason=request.reason, before_state={"on_hand": str(before)},
        after_state={"on_hand": str(after)},
        metadata={"product_id": product.pk, "adjustment_id": request.pk, "review_reason": review_reason},
    )
    return request


@transaction.atomic
def consume_service_requirements(*, sale_line, actor):
    """Deduct configured consumables when a service sale line is completed."""
    if not sale_line.service_id:
        return []
    movements = []
    requirements = list(
        sale_line.service.consumable_requirements.filter(active=True).select_related("product").order_by("product_id")
    )
    for requirement in requirements:
        product = Product.objects.select_for_update().get(pk=requirement.product_id)
        quantity = (requirement.quantity_per_service * Decimal(sale_line.quantity)).quantize(UNIT)
        if product.on_hand < quantity:
            raise ValidationError({"inventory": f"Not enough {product.name} to complete {sale_line.description}. Available: {product.on_hand}; required: {quantity}."})
        before = product.on_hand
        product.on_hand = before - quantity
        product.save(update_fields=("on_hand",))
        movement = InventoryMovement.objects.create(
            product=product, movement_type=InventoryMovement.Type.SERVICE_USE,
            quantity_delta=-quantity, sale_line=sale_line, actor=actor,
            reason=f"Consumables used to complete Sale #{sale_line.sale_id} service line #{sale_line.pk}.",
        )
        record_audit_event(
            event_type=AuditEvent.EventType.SALE_STOCK_DEDUCTION,
            object_type="inventory_movement", object_id=movement.pk, actor=actor,
            reason=movement.reason, before_state={"on_hand": str(before)}, after_state={"on_hand": str(product.on_hand)},
            metadata={"product_id": product.pk, "sale_id": sale_line.sale_id, "sale_line_id": sale_line.pk, "service_id": sale_line.service_id},
        )
        movements.append(movement)
    return movements


@transaction.atomic
def receive_stock(*, product, quantity, unit_cost, reason, actor):
    """Record a supplier receipt as an immutable inbound stock movement."""
    from decimal import InvalidOperation
    CENT = Decimal("0.01")
    from accounts.models import User

    product_id = product.pk if isinstance(product, Product) else product
    if not (actor.is_superuser or getattr(actor, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise ValidationError({"actor": "Only an owner or manager can receive stock."})
    quantity = _quantity(quantity)
    if quantity <= 0:
        raise ValidationError({"quantity": "Received stock quantity must be positive."})
    try:
        cost = Decimal(str(unit_cost))
        rounded_cost = cost.quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"unit_cost": "Enter a valid KSh unit cost."}) from None
    if not cost.is_finite() or cost != rounded_cost or rounded_cost < 0:
        raise ValidationError({"unit_cost": "Unit cost must be non-negative with at most two decimal places."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record the supplier receipt or purchase reason."})
    try:
        locked_product = Product.objects.select_for_update().get(pk=product_id)
    except (Product.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"product": "Choose a valid product."}) from None
    before, old_cost = locked_product.on_hand, locked_product.cost_price
    locked_product.on_hand = before + quantity
    locked_product.cost_price = rounded_cost
    locked_product.save(update_fields=("on_hand", "cost_price"))
    movement = InventoryMovement.objects.create(
        product=locked_product, movement_type=InventoryMovement.Type.PURCHASE,
        quantity_delta=quantity, unit_cost=rounded_cost, actor=actor, reason=reason,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.STOCK_ADJUSTMENT, object_type="inventory_movement",
        object_id=movement.pk, actor=actor, reason=reason,
        before_state={"on_hand": str(before), "cost_price": str(old_cost)},
        after_state={"on_hand": str(locked_product.on_hand), "cost_price": str(rounded_cost)},
        metadata={"product_id": locked_product.pk, "movement_type": InventoryMovement.Type.PURCHASE},
    )
    return movement
