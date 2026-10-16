from django.conf import settings
from django.db import models
from django.db.models import Q
from audit.models import ImmutableManager


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
    objects = ImmutableManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(quantity_delta__gt=0) | Q(quantity_delta__lt=0), name="inventory_movement_delta_nonzero"),
            models.UniqueConstraint(fields=("sale_line",), condition=Q(movement_type="SALE", sale_line__isnull=False), name="inventory_one_sale_movement_per_line"),
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
