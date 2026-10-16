from django.conf import settings
from django.db import models


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Audit and ledger records are immutable.")

    def delete(self):
        raise TypeError("Audit and ledger records are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("Audit and ledger records are immutable.")


ImmutableManager = models.Manager.from_queryset(ImmutableQuerySet)


class AuditEvent(models.Model):
    class EventType(models.TextChoices):
        STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT", "Stock adjustment"
        PAYMENT_RECONCILIATION = "PAYMENT_RECONCILIATION", "Payment reconciliation"
        REFUND = "REFUND", "Refund"
        PAYOUT = "PAYOUT", "Payout"
        APPROVAL = "APPROVAL", "Approval"
        SALE_STOCK_DEDUCTION = "SALE_STOCK_DEDUCTION", "Sale stock deduction"
        SERVICE_COMPLETION = "SERVICE_COMPLETION", "Service completion"
        COMMISSION_ADJUSTMENT = "COMMISSION_ADJUSTMENT", "Commission adjustment"
        PRODUCT_IMPORT = "PRODUCT_IMPORT", "Product import"

    event_type = models.CharField(max_length=40, choices=EventType.choices)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_events"
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approved_audit_events",
    )
    reason = models.TextField(blank=True)
    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("event_type", "created_at"), name="audit_type_created_idx"),
            models.Index(fields=("object_type", "object_id"), name="audit_object_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Audit events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Audit events are immutable.")

    def __str__(self):
        return f"{self.event_type} {self.object_type} #{self.object_id}"
