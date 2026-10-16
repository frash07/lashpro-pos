from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from audit.models import ImmutableManager


class CommissionLedgerEntry(models.Model):
    class Type(models.TextChoices):
        EARNED = "EARNED", "Earned"
        REVERSAL = "REVERSAL", "Reversal"

    entry_type = models.CharField(max_length=10, choices=Type.choices)
    sale_line = models.ForeignKey("sales.SaleLine", on_delete=models.PROTECT, related_name="commission_entries")
    refund_line = models.OneToOneField("sales.SaleRefundLine", on_delete=models.PROTECT, null=True, blank=True, related_name="commission_reversal")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_ledger_entries")
    base_amount = models.DecimalField(max_digits=10, decimal_places=2)
    rate_snapshot = models.DecimalField(max_digits=5, decimal_places=4)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_entries_created")
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("sale_line",), condition=Q(entry_type="EARNED"), name="commission_one_earned_per_line"),
            models.CheckConstraint(condition=Q(entry_type="EARNED", amount__gt=0) | Q(entry_type="REVERSAL", amount__lt=0), name="commission_entry_sign_matches_type"),
            models.CheckConstraint(condition=Q(rate_snapshot__gte=0, rate_snapshot__lte=1), name="commission_rate_snapshot_range"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Commission ledger entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Commission ledger entries are immutable.")

    def __str__(self):
        return f"{self.get_entry_type_display()} · {self.technician} · KSh {self.amount}"


class CommissionPayoutRequest(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Awaiting approval"
        ISSUED = "ISSUED", "Issued"
        REJECTED = "REJECTED", "Rejected"

    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_payout_requests")
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=50, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_payouts_requested")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="commission_payouts_reviewed")
    review_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="commission_payout_request_positive"),
            models.UniqueConstraint(Lower("reference"), condition=Q(method="MPESA") & ~Q(reference=""), name="commission_request_mpesa_ref_ci_unique"),
        ]

    def __str__(self):
        return f"Payout request · {self.technician} · KSh {self.amount}"


class CommissionPayoutRecord(models.Model):
    request = models.OneToOneField(CommissionPayoutRequest, on_delete=models.PROTECT, related_name="payout_record")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_payout_records")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=10, choices=CommissionPayoutRequest.Method.choices)
    reference = models.CharField(max_length=50, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commission_payouts_issued")
    cash_session = models.ForeignKey("payments.CashSession", on_delete=models.PROTECT, null=True, blank=True, related_name="commission_payouts")
    issued_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("reference"), condition=Q(method="MPESA") & ~Q(reference=""), name="commission_payout_mpesa_ref_ci_unique"),
        ]

    @property
    def verification_status(self):
        if self.method == CommissionPayoutRequest.Method.CASH:
            return "CONFIRMED"
        from payments.models import PayoutReconciliation
        try:
            return self.payout_reconciliation.decision
        except PayoutReconciliation.DoesNotExist:
            return "UNVERIFIED"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Commission payout records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Commission payout records are immutable.")

    def __str__(self):
        return f"Commission payout · {self.technician} · KSh {self.amount}"
