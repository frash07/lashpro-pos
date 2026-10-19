from decimal import Decimal
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum

from catalog.models import Product, Service
from customers.models import Customer

ZERO = Decimal("0.00")


def generate_receipt_number():
    return "LP-" + secrets.token_hex(8).upper()


def generate_receipt_token():
    return secrets.token_urlsafe(32)

class Sale(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    receipt_number = models.CharField(max_length=20, unique=True, default=generate_receipt_number, editable=False)
    receipt_token = models.CharField(max_length=64, unique=True, default=generate_receipt_token, editable=False)
    checkout_idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    @property
    def total_amount(self):
        if not self.pk:
            return ZERO
        return sum(
            (line.line_total() for line in self.lines.all()),
            ZERO,
        )

    @property
    def paid_amount(self):
        if not self.pk:
            return ZERO
        amount = self.payment_allocations.filter(
            payment_transaction__status="SUCCEEDED"
        ).aggregate(total=Sum("amount"))["total"]
        return amount or ZERO

    @property
    def unverified_amount(self):
        if not self.pk:
            return ZERO
        amount = self.payment_allocations.filter(
            payment_transaction__status="UNVERIFIED"
        ).aggregate(total=Sum("amount"))["total"]
        return amount or ZERO

    @property
    def allocated_amount(self):
        if not self.pk:
            return ZERO
        amount = self.payment_allocations.filter(
            payment_transaction__status__in=("PENDING", "UNVERIFIED", "SUCCEEDED")
        ).aggregate(total=Sum("amount"))["total"]
        return amount or ZERO

    @property
    def available_to_collect(self):
        return max(self.total_amount - self.allocated_amount, ZERO)

    @property
    def refunded_amount(self):
        if not self.pk:
            return ZERO
        amount = self.refunds.filter(status="ISSUED").aggregate(total=Sum("amount"))["total"]
        return amount or ZERO

    @property
    def net_total(self):
        return max(self.total_amount - self.refunded_amount, ZERO)

    @property
    def net_paid_amount(self):
        return max(self.paid_amount - self.refunded_amount, ZERO)

    @property
    def balance_due(self):
        return max(self.total_amount - self.paid_amount, ZERO)

    def __str__(self):
        return self.receipt_number or "Unsaved sale"


class SaleLine(models.Model):
    class LineType(models.TextChoices):
        PRODUCT = "PRODUCT", "Retail product"
        SERVICE = "SERVICE", "Salon service"
        TRAINING = "TRAINING", "Training tuition"

    sale = models.ForeignKey(
        Sale,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        related_name="sale_lines",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    service = models.ForeignKey(
        Service,
        related_name="sale_lines",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    line_type = models.CharField(max_length=12, choices=LineType.choices, default=LineType.PRODUCT)
    # Snapshots preserve the sold name and price if the catalog later changes.
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(ZERO)],
    )
    # Discount is the total discount for this line, not a per-unit discount.
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    commission_eligible_snapshot = models.BooleanField(default=False)
    commission_rate_snapshot = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0000"))
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="assigned_sale_lines",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="completed_sale_lines",
    )
    service_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(line_type="PRODUCT", product__isnull=False, service__isnull=True)
                    | Q(line_type="SERVICE", product__isnull=True, service__isnull=False)
                    | Q(line_type="TRAINING", product__isnull=True, service__isnull=True)
                ),
                name="sales_line_matches_item_type",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        has_product = self.product_id is not None
        has_service = self.service_id is not None
        if self.line_type == self.LineType.PRODUCT and not (has_product and not has_service):
            errors["product"] = "A retail line must reference exactly one product."
        elif self.line_type == self.LineType.SERVICE and not (has_service and not has_product):
            errors["service"] = "A salon service line must reference exactly one service."
        elif self.line_type == self.LineType.TRAINING and (has_product or has_service):
            errors["line_type"] = "A training tuition line cannot reference a retail product or salon service."
        elif self.line_type not in self.LineType.values:
            errors["line_type"] = "Choose a valid sale line type."

        if self.line_type != self.LineType.SERVICE and (self.technician_id or self.completed_by_id or self.service_completed_at):
            errors["technician"] = "Only salon service lines can be assigned or completed by a technician."

        if self.quantity is not None and self.quantity < 1:
            errors["quantity"] = "Quantity must be at least 1."
        if self.unit_price is not None and self.unit_price < 0:
            errors["unit_price"] = "Unit price cannot be negative."
        if self.discount is not None and self.discount < 0:
            errors["discount"] = "Discount cannot be negative."
        if (
            self.quantity is not None
            and self.unit_price is not None
            and self.discount is not None
            and self.discount > self.quantity * self.unit_price
        ):
            errors["discount"] = "Discount cannot exceed the line subtotal."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def from_product(cls, *, sale, product, quantity=1, discount=ZERO):
        """Build a line with the product name and price snapshotted."""
        return cls(
            sale=sale,
            product=product,
            line_type=cls.LineType.PRODUCT,
            description=product.name,
            quantity=quantity,
            unit_price=product.selling_price,
            discount=discount,
        )

    @classmethod
    def from_service(cls, *, sale, service, quantity=1, discount=ZERO):
        """Build a line with the service name and price snapshotted."""
        return cls(
            sale=sale,
            service=service,
            line_type=cls.LineType.SERVICE,
            description=service.name,
            quantity=quantity,
            unit_price=service.price,
            discount=discount,
        )

    @classmethod
    def from_training_tuition(cls, *, sale, description, tuition_fee):
        """Build a tuition invoice line without classifying it as a salon service."""
        return cls(
            sale=sale,
            line_type=cls.LineType.TRAINING,
            description=description,
            quantity=1,
            unit_price=tuition_fee,
            discount=ZERO,
        )

    def line_total(self):
        return (self.quantity * self.unit_price) - self.discount

    def __str__(self):
        return f"{self.description} on Sale #{self.sale_id}"


class SaleRefund(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Awaiting manager approval"
        ISSUED = "ISSUED", "Issued"
        REJECTED = "REJECTED", "Rejected"

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=50, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_sale_refunds")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_sale_refunds")
    review_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at", "-pk")
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_refund_amount_positive")]

    def __str__(self):
        return f"Refund request for {self.sale.receipt_number} · KSh {self.amount}"


class SaleRefundLine(models.Model):
    refund = models.ForeignKey(SaleRefund, on_delete=models.PROTECT, related_name="lines")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="refund_lines")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    restock = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("refund", "sale_line"), name="sales_refund_line_unique"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sales_refund_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="sales_refund_line_amount_nonnegative"),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.sale_line.description}"
