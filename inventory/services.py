import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from catalog.models import Product
from .models import InventoryMovement, StockAdjustmentRequest, StockReceipt, StockReceiptLine, Supplier

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
def receive_stock(*, product, quantity, unit_cost, reason, actor, receipt_line=None):
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
    if receipt_line is not None:
        existing = InventoryMovement.objects.filter(receipt_line=receipt_line).first()
        if existing:
            return existing
    before, old_cost = locked_product.on_hand, locked_product.cost_price
    locked_product.on_hand = before + quantity
    locked_product.cost_price = rounded_cost
    locked_product.save(update_fields=("on_hand", "cost_price"))
    movement = InventoryMovement.objects.create(
        product=locked_product, movement_type=InventoryMovement.Type.PURCHASE,
        quantity_delta=quantity, unit_cost=rounded_cost, actor=actor, reason=reason,
        receipt_line=receipt_line,
    )
    record_audit_event(
        event_type=AuditEvent.EventType.STOCK_RECEIPT, object_type="inventory_movement",
        object_id=movement.pk, actor=actor,
        before_state={"on_hand": str(before), "cost_price": str(old_cost)},
        after_state={"on_hand": str(locked_product.on_hand), "cost_price": str(rounded_cost)},
        metadata={"product_id": locked_product.pk, "movement_type": InventoryMovement.Type.PURCHASE, "receipt_id": receipt_line.receipt_id if receipt_line else None},
    )
    return movement



def _receipt_payload_matches(receipt, *, supplier_id, reference_type, supplier_reference, delivery_note_number, received_date, notes, line_specs):
    if (
        receipt.supplier_id != supplier_id
        or receipt.reference_type != reference_type
        or receipt.supplier_reference != supplier_reference
        or receipt.delivery_note_number != delivery_note_number
        or receipt.received_date != received_date
        or receipt.notes != notes
    ):
        return False
    existing_lines = list(receipt.lines.order_by("product_id").values_list("product_id", "quantity", "unit_cost"))
    expected_lines = sorted(
        (row["product_id"], row["quantity"], row["unit_cost"]) for row in line_specs
    )
    return existing_lines == expected_lines


def receive_supplier_stock(
    *, supplier, reference_type, supplier_reference, delivery_note_number="",
    received_date=None, notes="", lines, actor, idempotency_key,
):
    """Post one supplier document and all its product lines as a single transaction.

    The same submission key is safe to retry. A supplier document reference is
    also unique per supplier and document type, preventing accidental re-entry.
    """
    if not getattr(actor, "is_active", False) or not (
        actor.is_superuser or getattr(actor, "role", None) in {User.Role.OWNER, User.Role.MANAGER}
    ):
        raise ValidationError({"actor": "Only an active owner or manager can receive supplier stock."})

    supplier_id = supplier.pk if isinstance(supplier, Supplier) else supplier
    try:
        supplier_id = int(supplier_id)
        key = idempotency_key if isinstance(idempotency_key, uuid.UUID) else uuid.UUID(str(idempotency_key))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({"idempotency_key": "Submit a valid receipt submission key."}) from None

    reference_type = str(reference_type or "").strip().upper()
    valid_types = {choice for choice, _label in StockReceipt.ReferenceType.choices}
    if reference_type not in valid_types:
        raise ValidationError({"reference_type": "Choose a valid supplier document type."})
    supplier_reference = (supplier_reference or "").strip().upper()
    if not supplier_reference:
        raise ValidationError({"supplier_reference": "Enter the supplier's invoice or document reference."})
    if len(supplier_reference) > 100:
        raise ValidationError({"supplier_reference": "Supplier document references must be 100 characters or fewer."})
    delivery_note_number = (delivery_note_number or "").strip().upper()
    if len(delivery_note_number) > 100:
        raise ValidationError({"delivery_note_number": "Delivery note references must be 100 characters or fewer."})
    notes = (notes or "").strip()
    if len(notes) > 2000:
        raise ValidationError({"notes": "Receipt notes must be 2,000 characters or fewer."})
    if received_date is None:
        received_date = timezone.localdate()
    elif isinstance(received_date, str):
        try:
            received_date = date.fromisoformat(received_date)
        except ValueError:
            raise ValidationError({"received_date": "Enter a valid received date."}) from None
    elif not isinstance(received_date, date):
        raise ValidationError({"received_date": "Enter a valid received date."})

    try:
        raw_lines = list(lines)
    except TypeError:
        raise ValidationError({"lines": "Provide at least one product line."}) from None
    if not raw_lines or len(raw_lines) > 50:
        raise ValidationError({"lines": "A supplier receipt must contain between 1 and 50 product lines."})

    line_specs, seen_products = [], set()
    for index, item in enumerate(raw_lines, start=1):
        if not isinstance(item, dict) or set(item) - {"product", "product_id", "quantity", "unit_cost"}:
            raise ValidationError({"lines": f"Supplier receipt line {index} contains unsupported fields."})
        product_value = item.get("product", item.get("product_id"))
        product_id = product_value.pk if isinstance(product_value, Product) else product_value
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise ValidationError({"lines": f"Choose a valid product on receipt line {index}."}) from None
        if product_id in seen_products:
            raise ValidationError({"lines": "A product may appear only once on a receipt. Combine duplicate product quantities."})
        seen_products.add(product_id)
        try:
            quantity = _quantity(item.get("quantity"))
        except ValidationError as exc:
            raise ValidationError({"lines": f"Receipt line {index}: {exc.messages[0]}"}) from None
        if quantity <= 0:
            raise ValidationError({"lines": f"Receipt line {index}: quantity must be greater than zero."})
        try:
            cost = Decimal(str(item.get("unit_cost")))
            rounded_cost = cost.quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError({"lines": f"Receipt line {index}: enter a valid KSh unit cost."}) from None
        if not cost.is_finite() or cost != rounded_cost or rounded_cost < 0:
            raise ValidationError({"lines": f"Receipt line {index}: unit cost must be non-negative with at most two decimal places."})
        line_specs.append({
            "product_id": product_id,
            "quantity": quantity,
            "unit_cost": rounded_cost,
        })
    line_specs.sort(key=lambda row: row["product_id"])

    try:
        with transaction.atomic():
            try:
                locked_supplier = Supplier.objects.select_for_update().get(pk=supplier_id, active=True)
            except (Supplier.DoesNotExist, TypeError, ValueError):
                raise ValidationError({"supplier": "Choose an active supplier."}) from None

            existing_key = StockReceipt.objects.filter(idempotency_key=key).first()
            if existing_key:
                if _receipt_payload_matches(
                    existing_key, supplier_id=supplier_id, reference_type=reference_type,
                    supplier_reference=supplier_reference, delivery_note_number=delivery_note_number,
                    received_date=received_date,
                    notes=notes, line_specs=line_specs,
                ):
                    return existing_key, False
                raise ValidationError({"idempotency_key": "This receipt submission key was already used for different receipt details."})

            duplicate = StockReceipt.objects.filter(
                supplier=locked_supplier,
                reference_type=reference_type,
                supplier_reference=supplier_reference,
            ).first()
            if duplicate:
                raise ValidationError({
                    "supplier_reference": f"This supplier document is already recorded as receipt #{duplicate.pk}."
                })

            products = {
                product.pk: product
                for product in Product.objects.select_for_update().filter(
                    pk__in=[row["product_id"] for row in line_specs]
                ).order_by("pk")
            }
            if len(products) != len(line_specs):
                raise ValidationError({"lines": "One or more selected products no longer exist. Refresh the form and try again."})
            inactive = [product.name for product in products.values() if not product.active]
            if inactive:
                raise ValidationError({"lines": "Inactive products cannot be received: " + ", ".join(inactive) + "."})

            receipt = StockReceipt(
                supplier=locked_supplier,
                reference_type=reference_type,
                supplier_reference=supplier_reference,
                delivery_note_number=delivery_note_number,
                received_date=received_date,
                received_by=actor,
                notes=notes,
                idempotency_key=key,
            )
            receipt.full_clean()
            receipt.save()

            for row in line_specs:
                product = products[row["product_id"]]
                receipt_line = StockReceiptLine(
                    receipt=receipt,
                    product=product,
                    quantity=row["quantity"],
                    unit_cost=row["unit_cost"],
                )
                receipt_line.full_clean()
                receipt_line.save()
                receive_stock(
                    product=product,
                    quantity=row["quantity"],
                    unit_cost=row["unit_cost"],
                    reason=f"Supplier receipt #{receipt.pk} · {locked_supplier.name} · {supplier_reference}",
                    actor=actor,
                    receipt_line=receipt_line,
                )

            record_audit_event(
                event_type=AuditEvent.EventType.STOCK_RECEIPT,
                object_type="supplier_stock_receipt",
                object_id=receipt.pk,
                actor=actor,
                reason=f"Supplier receipt {supplier_reference}",
                after_state={
                    "supplier_id": locked_supplier.pk,
                    "reference_type": reference_type,
                    "supplier_reference": supplier_reference,
                    "line_count": len(line_specs),
                    "total_cost": str(receipt.total_cost),
                },
                metadata={
                    "receipt_id": receipt.pk,
                    "supplier_id": locked_supplier.pk,
                    "movement_ids": list(receipt.lines.values_list("movement__pk", flat=True)),
                },
            )
            return receipt, True
    except IntegrityError:
        # A concurrent retry may race after both requests pass the initial
        # lookup. The unique database constraints remain the final authority.
        existing_key = StockReceipt.objects.filter(idempotency_key=key).first()
        if existing_key and _receipt_payload_matches(
            existing_key, supplier_id=supplier_id, reference_type=reference_type,
            supplier_reference=supplier_reference, delivery_note_number=delivery_note_number,
            received_date=received_date,
            notes=notes, line_specs=line_specs,
        ):
            return existing_key, False
        duplicate = StockReceipt.objects.filter(
            supplier_id=supplier_id,
            reference_type=reference_type,
            supplier_reference=supplier_reference,
        ).first()
        if duplicate:
            raise ValidationError({
                "supplier_reference": f"This supplier document is already recorded as receipt #{duplicate.pk}."
            }) from None
        raise
