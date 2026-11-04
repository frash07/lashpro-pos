import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from audit.models import ImmutableManager


class Supplier(models.Model):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="inventory_supplier_name_ci_uniq"),
        ]

    def clean(self):
        super().clean()
        self.name = (self.name or "").strip()

    def __str__(self):
        return self.name


class StockReceipt(models.Model):
    class ReferenceType(models.TextChoices):
        INVOICE = "INVOICE", "Supplier invoice"
        DELIVERY_NOTE = "DELIVERY_NOTE", "Delivery note"
        CASH_RECEIPT = "CASH_RECEIPT", "Cash receipt"
        OTHER = "OTHER", "Other supplier document"

    objects = ImmutableManager()

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="stock_receipts")
    reference_type = models.CharField(max_length=20, choices=ReferenceType.choices, default=ReferenceType.INVOICE)
    supplier_reference = models.CharField(max_length=100)
    delivery_note_number = models.CharField(max_length=100, blank=True)
    received_date = models.DateField(default=timezone.localdate)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="supplier_stock_receipts")
    notes = models.TextField(blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_date", "-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("supplier", "reference_type", "supplier_reference"),
                name="inventory_supplier_receipt_reference_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        self.supplier_reference = (self.supplier_reference or "").strip().upper()
        self.delivery_note_number = (self.delivery_note_number or "").strip().upper()
        if not self.supplier_reference:
            raise ValidationError({"supplier_reference": "Enter the supplier's invoice or document reference."})

    @property
    def total_cost(self):
        from decimal import Decimal
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Supplier receipts are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Supplier receipts are immutable.")

    def __str__(self):
        return f"{self.supplier} · {self.supplier_reference}"


class StockReceiptLine(models.Model):
    objects = ImmutableManager()

    receipt = models.ForeignKey(StockReceipt, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="supplier_receipt_lines")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ("pk",)
        constraints = [
            models.UniqueConstraint(fields=("receipt", "product"), name="inventory_receipt_product_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inventory_receipt_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="inventory_receipt_cost_nonnegative"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Supplier receipt lines are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Supplier receipt lines are immutable.")

    @property
    def line_total(self):
        return self.quantity * self.unit_cost

    def __str__(self):
        return f"{self.quantity} × {self.product} on receipt #{self.receipt_id}"


class InventoryMovement(models.Model):
    class Type(models.TextChoices):
        PURCHASE = "PURCHASE", "Purchase receipt"
        SALE = "SALE", "Product sale"
        RETURN = "RETURN", "Customer return"
        SERVICE_USE = "SERVICE_USE", "Service consumable"
        ADJUSTMENT = "ADJUSTMENT", "Approved adjustment"
        REVERSAL = "REVERSAL", "Reversal"

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="stock_movements")
    movement_type = models.CharField(max_length=20, choices=Type.choices)
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sale_line = models.ForeignKey("sales.SaleLine", on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_movements")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    source_adjustment = models.OneToOneField("inventory.StockAdjustmentRequest", on_delete=models.PROTECT, null=True, blank=True, related_name="movement")
    receipt_line = models.OneToOneField("inventory.StockReceiptLine", on_delete=models.PROTECT, null=True, blank=True, related_name="movement")
    objects = ImmutableManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(quantity_delta__gt=0) | Q(quantity_delta__lt=0), name="inventory_movement_delta_nonzero"),
            models.UniqueConstraint(fields=("sale_line",), condition=Q(movement_type="SALE", sale_line__isnull=False), name="inventory_one_sale_movement_per_line"),
            models.CheckConstraint(condition=Q(receipt_line__isnull=True) | Q(movement_type="PURCHASE"), name="inventory_receipt_line_purchase_only"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Inventory movements are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Inventory movements are immutable.")

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity_delta} {self.product}"


class StockAdjustmentRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="adjustment_requests")
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.TextField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_adjustment_requests")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_adjustment_reviews")
    review_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(quantity_delta__gt=0) | Q(quantity_delta__lt=0), name="inventory_adjustment_delta_nonzero"),
        ]

    def __str__(self):
        return f"Adjustment #{self.pk} · {self.product} ({self.get_status_display()})"


class ServiceConsumable(models.Model):
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="consumable_requirements")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="service_requirements")
    quantity_per_service = models.DecimalField(max_digits=12, decimal_places=3)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("service", "product"), name="inventory_unique_service_consumable"),
            models.CheckConstraint(condition=Q(quantity_per_service__gt=0), name="inventory_service_consumable_positive"),
        ]
        ordering = ("service__name", "product__name")

    def __str__(self):
        return f"{self.service}: {self.quantity_per_service} × {self.product}"
