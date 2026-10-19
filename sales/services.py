from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import User
from catalog.models import Product, Service
from payments.models import PaymentTransaction, SalePayment
from .models import Sale, SaleLine

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_AMOUNT = Decimal("99999999.99")
ACTIVE_PAYMENT_STATUSES = (
    PaymentTransaction.Status.PENDING,
    PaymentTransaction.Status.UNVERIFIED,
    PaymentTransaction.Status.SUCCEEDED,
)


def _money(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "Enter a valid KSh amount."}) from None
    if not amount.is_finite():
        raise ValidationError({field: "Enter a finite KSh amount."})
    try:
        rounded = amount.quantize(CENT)
    except InvalidOperation:
        raise ValidationError({field: "Enter a valid KSh amount."}) from None
    if rounded != amount or abs(rounded) > MAX_AMOUNT:
        raise ValidationError({field: "Amount must fit KSh with at most two decimal places."})
    return rounded


def _positive_integer(value, field):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "Enter a whole-number quantity of at least 1."}) from None
    if (
        not number.is_finite()
        or number != number.to_integral_value()
        or number < 1
        or number > 2147483647
    ):
        raise ValidationError({field: "Enter a whole-number quantity of at least 1."})
    return int(number)


def _positive_id(value, field):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "Select a valid catalog item."}) from None
    if not number.is_finite() or number != number.to_integral_value() or number < 1:
        raise ValidationError({field: "Select a valid catalog item."})
    return int(number)


def _create_sale_line(*, sale, item):
    if not isinstance(item, Mapping):
        raise ValidationError({"items": "Each sale line must be an item mapping."})

    allowed_keys = {"product_id", "service_id", "quantity", "discount", "technician_id", "discount_reason"}
    unknown_keys = set(item) - allowed_keys
    if unknown_keys:
        raise ValidationError({"items": f"Unsupported sale-line fields: {', '.join(sorted(unknown_keys))}."})

    has_product = "product_id" in item
    has_service = "service_id" in item
    if has_product == has_service:
        raise ValidationError({"items": "Each line must specify exactly one product_id or service_id."})

    quantity = _positive_integer(item.get("quantity", 1), "quantity")
    discount = _money(item.get("discount", ZERO), "discount")
    if discount < ZERO:
        raise ValidationError({"discount": "Discount cannot be negative."})
    discount_reason = str(item.get("discount_reason", "") or "").strip()
    if discount > ZERO:
        if not discount_reason:
            raise ValidationError({"discount_reason": "A manager must record a reason for every discount."})
        if not (
            sale.cashier.is_superuser
            or sale.cashier.role in {User.Role.OWNER, User.Role.MANAGER}
        ):
            raise ValidationError({"discount": "Only an owner or manager may approve a discount."})

    technician_id = item.get("technician_id")
    if has_product and technician_id not in (None, ""):
        raise ValidationError({"technician_id": "Only service lines can have an assigned technician."})

    if has_product:
        product_id = _positive_id(item["product_id"], "product_id")
        try:
            product = Product.objects.select_for_update().get(pk=product_id, active=True)
        except Product.DoesNotExist:
            raise ValidationError({"product_id": "The selected product is unavailable."}) from None
        line = SaleLine.from_product(
            sale=sale,
            product=product,
            quantity=quantity,
            discount=discount,
        )
    else:
        service_id = _positive_id(item["service_id"], "service_id")
        try:
            service = Service.objects.get(pk=service_id, active=True)
        except Service.DoesNotExist:
            raise ValidationError({"service_id": "The selected service is unavailable."}) from None
        line = SaleLine.from_service(
            sale=sale,
            service=service,
            quantity=quantity,
            discount=discount,
        )
        line.commission_eligible_snapshot = service.commission_eligible
        line.commission_rate_snapshot = service.commission_rate if service.commission_eligible else Decimal("0.0000")
        if technician_id not in (None, ""):
            technician_pk = _positive_id(technician_id, "technician_id")
            try:
                line.technician = User.objects.get(
                    pk=technician_pk, role=User.Role.TECHNICIAN, is_active=True
                )
            except User.DoesNotExist:
                raise ValidationError({"technician_id": "Choose an active lash technician."}) from None

    if discount > line.unit_price * line.quantity:
        raise ValidationError({"discount": "Discount cannot exceed the line subtotal."})
    line.full_clean()
    line.save()
    if discount > ZERO:
        from audit.models import AuditEvent
        from audit.services import record_audit_event
        record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="sale_line_discount",
            object_id=line.pk,
            actor=sale.cashier,
            reason=discount_reason,
            after_state={"discount": str(discount), "line_total": str(line.line_total())},
            metadata={"sale_id": sale.pk, "sale_line_id": line.pk},
        )
    if line.product_id:
        from inventory.services import deduct_product_for_sale_line
        deduct_product_for_sale_line(sale_line=line, actor=sale.cashier)
    return line


@transaction.atomic
def record_sale_payment(*, sale, method, amount, reference="", actor=None, idempotency_key=None):
    """Record a cash or manually entered M-Pesa payment against a completed sale.

    A caller-supplied key makes a repeated cashier form submission safe. The
    payment row and sale allocation are created together in a savepoint.
    """
    sale_id = sale.pk if isinstance(sale, Sale) else sale
    try:
        locked_sale = Sale.objects.select_for_update().get(pk=sale_id)
    except (Sale.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"sale": "Sale does not exist."}) from None

    if locked_sale.status != Sale.Status.COMPLETED:
        raise ValidationError({"sale": "Payments can only be recorded against a completed sale."})

    collector = actor or locked_sale.cashier
    if not getattr(collector, "is_active", False):
        raise ValidationError({"actor": "Choose an active staff member to record the payment."})
    if not (
        collector.is_superuser
        or collector.role in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}
    ):
        raise ValidationError({"actor": "Only an owner, manager, or cashier can record a sale payment."})

    try:
        method = PaymentTransaction.Method(str(method).upper())
    except ValueError:
        raise ValidationError({"method": "Choose Cash or M-Pesa."}) from None

    payment_amount = _money(amount, "amount")
    if payment_amount <= ZERO:
        raise ValidationError({"amount": "Payment amount must be greater than zero."})

    reference = (reference or "").strip().upper()
    if method == PaymentTransaction.Method.MPESA:
        if not reference:
            raise ValidationError({"reference": "Enter the manual M-Pesa transaction reference."})
        status = PaymentTransaction.Status.UNVERIFIED
    else:
        status = PaymentTransaction.Status.SUCCEEDED

    if len(reference) > 50:
        raise ValidationError({"reference": "Reference must be 50 characters or fewer."})

    key = _normalize_idempotency_key(idempotency_key)
    existing = PaymentTransaction.objects.filter(idempotency_key=key).first()
    if existing:
        allocation = SalePayment.objects.filter(payment_transaction=existing).first()
        if (
            allocation
            and allocation.sale_id == locked_sale.pk
            and existing.amount == payment_amount
            and existing.method == method
            and existing.reference == reference
            and existing.recorded_by_id in (None, collector.pk)
        ):
            return existing
        raise ValidationError({"idempotency_key": "This payment form was already used for a different payment."})

    if method == PaymentTransaction.Method.MPESA and PaymentTransaction.objects.filter(
        method=method, reference__iexact=reference
    ).exists():
        raise ValidationError({"reference": "This M-Pesa reference has already been recorded."})

    already_allocated = SalePayment.objects.filter(
        sale=locked_sale,
        payment_transaction__status__in=ACTIVE_PAYMENT_STATUSES,
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    remaining_balance = max(locked_sale.total_amount - already_allocated, ZERO)
    if remaining_balance <= ZERO:
        raise ValidationError({"amount": "This sale has no balance due."})
    if method == PaymentTransaction.Method.MPESA and payment_amount > remaining_balance:
        raise ValidationError({"amount": "M-Pesa payment cannot exceed the sale balance."})
    # For cash, PaymentTransaction.amount records the notes received, while
    # SalePayment.amount records only the amount applied to the sale.
    # The difference is change returned to the customer.
    allocation_amount = min(payment_amount, remaining_balance) if method == PaymentTransaction.Method.CASH else payment_amount

    cash_session = None
    if method == PaymentTransaction.Method.CASH:
        from payments.models import CashSession
        cash_session = CashSession.objects.select_for_update().filter(
            cashier=collector, status=CashSession.Status.OPEN,
        ).first()
        if cash_session is None:
            raise ValidationError({"cash_session": "Open a cash session before accepting cash."})

    payment = PaymentTransaction(
        amount=payment_amount,
        method=method,
        status=status,
        reference=reference,
        idempotency_key=key,
        recorded_by=collector,
        cash_session=cash_session,
    )
    try:
        with transaction.atomic():
            payment.full_clean()
            payment.save()
            allocation = SalePayment(
                sale=locked_sale,
                payment_transaction=payment,
                amount=allocation_amount,
            )
            allocation.full_clean()
            allocation.save()
    except IntegrityError:
        existing = PaymentTransaction.objects.filter(idempotency_key=key).first()
        if existing:
            allocation = SalePayment.objects.filter(payment_transaction=existing).first()
            if (
                allocation
                and allocation.sale_id == locked_sale.pk
                and existing.amount == payment_amount
                and existing.method == method
                and existing.reference == reference
                and existing.recorded_by_id in (None, collector.pk)
            ):
                return existing
            raise ValidationError({"idempotency_key": "This payment form was already used for a different payment."}) from None
        if method == PaymentTransaction.Method.MPESA and PaymentTransaction.objects.filter(
            method=method, reference__iexact=reference
        ).exists():
            raise ValidationError({"reference": "This M-Pesa reference has already been recorded."}) from None
        raise
    from training.models import Enrollment
    enrollment = Enrollment.objects.filter(sale=locked_sale).first()
    if enrollment:
        from training.services import sync_enrollment_payment_status
        sync_enrollment_payment_status(enrollment)
    return payment


def _normalize_idempotency_key(value):
    if value in (None, ""):
        return uuid.uuid4()
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise ValidationError({"idempotency_key": "Submit a valid checkout key."}) from None


def checkout_sale(*, cashier, items, customer=None, payments=(), idempotency_key=None):
    """Create one completed sale for a checkout key, even if a request is retried."""
    if not getattr(cashier, "is_active", False) or not (
        cashier.is_superuser
        or cashier.role in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}
    ):
        raise ValidationError({"cashier": "Only an active owner, manager, or cashier can create a sale."})
    key = _normalize_idempotency_key(idempotency_key)
    existing = Sale.objects.filter(checkout_idempotency_key=key).first()
    if existing:
        if existing.cashier_id != cashier.pk:
            raise ValidationError({"idempotency_key": "This checkout key belongs to another cashier."})
        return existing

    try:
        return _create_checkout_sale(
            cashier=cashier, items=items, customer=customer, payments=payments,
            idempotency_key=key,
        )
    except IntegrityError:
        # A concurrent retry can pass the initial lookup; the unique database
        # constraint makes the second request wait for the first transaction.
        existing = Sale.objects.filter(checkout_idempotency_key=key).first()
        if existing and existing.cashier_id == cashier.pk:
            return existing
        if existing:
            raise ValidationError({"idempotency_key": "This checkout key belongs to another cashier."}) from None
        raise


@transaction.atomic
def _create_checkout_sale(*, cashier, items, customer, payments, idempotency_key):
    try:
        item_specs = list(items)
    except TypeError:
        raise ValidationError({"items": "Provide one or more sale lines."}) from None
    if not item_specs:
        raise ValidationError({"items": "A sale must contain at least one line."})
    try:
        payment_specs = list(payments or ())
    except TypeError:
        raise ValidationError({"payments": "Provide a list of payments."}) from None

    product_ids = {
        _positive_id(item["product_id"], "product_id")
        for item in item_specs
        if isinstance(item, Mapping) and "product_id" in item
    }
    # Acquire product locks in a stable order before processing the cart.
    list(Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk"))

    sale = Sale.objects.create(
        cashier=cashier, customer=customer, checkout_idempotency_key=idempotency_key
    )
    for item in item_specs:
        _create_sale_line(sale=sale, item=item)

    sale.status = Sale.Status.COMPLETED
    sale.save(update_fields=("status",))

    # Process M-Pesa allocations before cash so a cash tender can correctly
    # cover the remaining balance and calculate change independent of form order.
    ordered_payment_specs = sorted(
        payment_specs,
        key=lambda item: 0 if isinstance(item, Mapping) and str(item.get("method", "")).upper() == PaymentTransaction.Method.MPESA else 1,
    )
    for payment in ordered_payment_specs:
        if not isinstance(payment, Mapping):
            raise ValidationError({"payments": "Each payment must be a mapping."})
        extra_keys = set(payment) - {"method", "amount", "reference"}
        if extra_keys:
            raise ValidationError({"payments": "Payments accept only method, amount, and reference."})
        record_sale_payment(
            sale=sale,
            method=payment.get("method"),
            amount=payment.get("amount"),
            reference=payment.get("reference", ""),
        )

    return sale


@transaction.atomic
def request_sale_refund(*, sale, items, method, reason, requested_by, reference=""):
    """Queue a line-based refund for independent manager approval."""
    from decimal import ROUND_HALF_UP
    from accounts.models import User
    from audit.models import AuditEvent
    from audit.services import record_audit_event
    from .models import SaleRefund, SaleRefundLine

    sale_id = sale.pk if isinstance(sale, Sale) else sale
    try:
        locked_sale = Sale.objects.select_for_update().get(pk=sale_id)
    except (Sale.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"sale": "Sale not found."}) from None
    if locked_sale.status != Sale.Status.COMPLETED:
        raise ValidationError({"sale": "Only completed sales can be refunded."})
    if not (requested_by.is_superuser or getattr(requested_by, "role", None) in {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}):
        raise ValidationError({"requested_by": "You may not request a sale refund."})
    try:
        method = SaleRefund.Method(str(method).upper())
    except ValueError:
        raise ValidationError({"method": "Choose cash or M-Pesa."}) from None
    reason, reference = (reason or "").strip(), (reference or "").strip().upper()
    if not reason:
        raise ValidationError({"reason": "Explain why this refund is requested."})
    if method == SaleRefund.Method.MPESA and not reference:
        raise ValidationError({"reference": "Enter the M-Pesa refund payout reference."})
    if len(reference) > 50:
        raise ValidationError({"reference": "Reference must be 50 characters or fewer."})
    try:
        item_specs = list(items)
    except TypeError:
        raise ValidationError({"items": "Provide one or more sale lines to refund."}) from None
    if not item_specs:
        raise ValidationError({"items": "Choose at least one sale line to refund."})

    refund_lines, refund_total, seen = [], ZERO, set()
    for item in item_specs:
        if not isinstance(item, Mapping) or set(item) - {"sale_line_id", "quantity", "restock"}:
            raise ValidationError({"items": "Refund lines accept sale_line_id, quantity, and restock."})
        line_id = _positive_id(item.get("sale_line_id"), "sale_line_id")
        if line_id in seen:
            raise ValidationError({"items": "Each sale line may appear once per refund."})
        seen.add(line_id)
        quantity = _positive_integer(item.get("quantity", 1), "quantity")
        line = SaleLine.objects.select_for_update().filter(pk=line_id, sale=locked_sale).first()
        if line is None:
            raise ValidationError({"sale_line_id": "Choose a line from this sale."})
        previous = SaleRefundLine.objects.filter(sale_line=line).exclude(
            refund__status=SaleRefund.Status.REJECTED,
        ).aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
        previous_quantity, previous_amount = previous["quantity"] or 0, previous["amount"] or ZERO
        remaining_quantity, remaining_amount = line.quantity - previous_quantity, line.line_total() - previous_amount
        if quantity > remaining_quantity:
            raise ValidationError({"quantity": f"Only {remaining_quantity} unit(s) remain refundable for {line.description}."})
        restock = bool(item.get("restock", False))
        if restock and not line.product_id:
            raise ValidationError({"restock": "Only returned products can be restocked."})
        if quantity == remaining_quantity:
            line_amount = remaining_amount
        else:
            line_amount = (line.line_total() * Decimal(quantity) / Decimal(line.quantity)).quantize(CENT, rounding=ROUND_HALF_UP)
        if line_amount < ZERO:
            raise ValidationError({"items": "Refund allocation cannot be negative."})
        refund_lines.append((line, quantity, line_amount, restock))
        refund_total += line_amount
    refund_total = refund_total.quantize(CENT)
    if refund_total <= ZERO:
        raise ValidationError({"items": "Selected sale lines have no refundable value."})

    collected = SalePayment.objects.filter(
        sale=locked_sale, payment_transaction__method=method,
        payment_transaction__status=PaymentTransaction.Status.SUCCEEDED,
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    reserved = SaleRefund.objects.filter(
        sale=locked_sale, method=method,
        status__in=(SaleRefund.Status.REQUESTED, SaleRefund.Status.ISSUED),
    ).aggregate(total=Sum("amount"))["total"] or ZERO
    if refund_total + reserved > collected:
        raise ValidationError({"amount": f"Refund exceeds confirmed {method} payments available for this sale."})

    refund = SaleRefund.objects.create(
        sale=locked_sale, amount=refund_total, method=method, reference=reference,
        reason=reason, requested_by=requested_by,
    )
    for line, quantity, amount, restock in refund_lines:
        SaleRefundLine.objects.create(refund=refund, sale_line=line, quantity=quantity, amount=amount, restock=restock)
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="sale_refund",
        object_id=refund.pk, actor=requested_by, reason=reason,
        after_state={"status": refund.status, "amount": str(refund.amount), "method": method},
        metadata={"sale_id": locked_sale.pk, "receipt_number": locked_sale.receipt_number},
    )
    return refund


@transaction.atomic
def issue_refund(*, refund, approver, review_reason=""):
    """Manager approval and payout issuance for a previously requested refund."""
    from accounts.models import User
    from audit.models import AuditEvent
    from audit.services import record_audit_event
    from inventory.models import InventoryMovement
    from payments.models import CashSession, RefundPayout
    from .models import SaleRefund

    refund_id = refund.pk if isinstance(refund, SaleRefund) else refund
    try:
        locked = SaleRefund.objects.select_for_update().select_related("sale", "requested_by").get(pk=refund_id)
    except (SaleRefund.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"refund": "Refund request not found."}) from None
    if locked.status != SaleRefund.Status.REQUESTED:
        raise ValidationError({"refund": "This refund has already been reviewed."})
    if not (approver.is_superuser or getattr(approver, "role", None) in {User.Role.OWNER, User.Role.MANAGER}):
        raise ValidationError({"approver": "Only an owner or manager can issue a refund."})
    if locked.requested_by_id == approver.pk:
        raise ValidationError({"approver": "A different owner or manager must approve this refund."})
    if locked.method == SaleRefund.Method.MPESA:
        from commissions.models import CommissionPayoutRecord
        if (
            PaymentTransaction.objects.filter(method="MPESA", reference__iexact=locked.reference).exists()
            or RefundPayout.objects.filter(method="MPESA", reference__iexact=locked.reference).exists()
            or CommissionPayoutRecord.objects.filter(method="MPESA", reference__iexact=locked.reference).exists()
        ):
            raise ValidationError({"reference": "This M-Pesa reference is already in use."})
    cash_session = None
    if locked.method == SaleRefund.Method.CASH:
        cash_session = CashSession.objects.select_for_update().filter(cashier=approver, status=CashSession.Status.OPEN).first()
        if cash_session is None:
            raise ValidationError({"cash_session": "Open a cash session before issuing a cash refund."})

    reason = (review_reason or locked.reason).strip()
    payout = RefundPayout.objects.create(
        refund=locked, method=locked.method, amount=locked.amount,
        reference=locked.reference, issued_by=approver, cash_session=cash_session,
    )
    locked.status, locked.reviewed_by = SaleRefund.Status.ISSUED, approver
    locked.review_reason, locked.reviewed_at = reason, timezone.now()
    locked.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))

    from training.models import Certificate, Enrollment
    training_enrollment = Enrollment.objects.select_for_update().filter(sale=locked.sale).first()
    if training_enrollment:
        if locked.sale.refunded_amount >= training_enrollment.tuition_fee:
            if training_enrollment.status != Enrollment.Status.WITHDRAWN:
                training_enrollment.status = Enrollment.Status.WITHDRAWN
                training_enrollment.withdrawn_at = timezone.now()
                training_enrollment.withdrawal_reason = reason
                training_enrollment.save(update_fields=("status", "withdrawn_at", "withdrawal_reason"))
            certificate = Certificate.objects.filter(enrollment=training_enrollment).first()
            if certificate and certificate.status == Certificate.Status.ISSUED:
                from training.services import revoke_certificate
                revoke_certificate(certificate=certificate, actor=approver, reason=reason)
        elif training_enrollment.status in (Enrollment.Status.PENDING_PAYMENT, Enrollment.Status.ENROLLED):
            from training.services import sync_enrollment_payment_status
            sync_enrollment_payment_status(training_enrollment)

    for refund_line in locked.lines.select_related("sale_line__product", "sale_line__service"):
        line = refund_line.sale_line
        if refund_line.restock and line.product_id:
            product = Product.objects.select_for_update().get(pk=line.product_id)
            before = product.on_hand
            delta = Decimal(refund_line.quantity).quantize(Decimal("0.001"))
            product.on_hand = before + delta
            product.save(update_fields=("on_hand",))
            movement = InventoryMovement.objects.create(
                product=product, movement_type=InventoryMovement.Type.RETURN,
                quantity_delta=delta, sale_line=line, actor=approver,
                reason=f"Restocked on refund #{locked.pk}.",
            )
            record_audit_event(
                event_type=AuditEvent.EventType.REFUND, object_type="inventory_movement",
                object_id=movement.pk, actor=locked.requested_by, approver=approver,
                reason=reason, before_state={"on_hand": str(before)}, after_state={"on_hand": str(product.on_hand)},
                metadata={"refund_id": locked.pk, "sale_id": locked.sale_id, "sale_line_id": line.pk},
            )
        if line.service_id:
            from commissions.services import reverse_commission_for_refund
            reverse_commission_for_refund(refund_line=refund_line, actor=approver)

    record_audit_event(
        event_type=AuditEvent.EventType.REFUND, object_type="sale_refund",
        object_id=locked.pk, actor=locked.requested_by, approver=approver,
        reason=reason, before_state={"status": SaleRefund.Status.REQUESTED},
        after_state={"status": SaleRefund.Status.ISSUED, "amount": str(locked.amount), "method": locked.method},
        metadata={"sale_id": locked.sale_id, "payout_id": payout.pk, "reference": payout.reference},
    )
    record_audit_event(
        event_type=AuditEvent.EventType.PAYOUT, object_type="refund_payout",
        object_id=payout.pk, actor=locked.requested_by, approver=approver,
        reason=reason, after_state={"amount": str(payout.amount), "method": payout.method, "verification_status": payout.verification_status},
        metadata={"refund_id": locked.pk, "sale_id": locked.sale_id, "reference": payout.reference},
    )
    return payout


@transaction.atomic
def reject_refund(*, refund, approver, reason):
    from accounts.models import User
    from audit.models import AuditEvent
    from audit.services import record_audit_event
    from .models import SaleRefund

    refund_id = refund.pk if isinstance(refund, SaleRefund) else refund
    try:
        locked = SaleRefund.objects.select_for_update().get(pk=refund_id)
    except (SaleRefund.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"refund": "Refund request not found."}) from None
    if locked.status != SaleRefund.Status.REQUESTED:
        raise ValidationError({"refund": "This refund has already been reviewed."})
    if not (approver.is_superuser or getattr(approver, "role", None) in {User.Role.OWNER, User.Role.MANAGER}) or locked.requested_by_id == approver.pk:
        raise ValidationError({"approver": "A different owner or manager must reject this refund."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Record why the refund was rejected."})
    locked.status, locked.reviewed_by = SaleRefund.Status.REJECTED, approver
    locked.review_reason, locked.reviewed_at = reason, timezone.now()
    locked.save(update_fields=("status", "reviewed_by", "review_reason", "reviewed_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL, object_type="sale_refund",
        object_id=locked.pk, actor=locked.requested_by, approver=approver,
        reason=reason, before_state={"status": SaleRefund.Status.REQUESTED},
        after_state={"status": SaleRefund.Status.REJECTED, "amount": str(locked.amount)},
        metadata={"sale_id": locked.sale_id},
    )
    return locked
