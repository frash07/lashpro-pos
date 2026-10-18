from decimal import Decimal
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from audit.models import ImmutableManager


class PaymentTransaction(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        UNVERIFIED = "UNVERIFIED", "Unverified"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        REVERSED = "REVERSED", "Reversed"

    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reference = models.CharField(max_length=50, blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="recorded_payment_transactions",
    )
    cash_session = models.ForeignKey(
        "payments.CashSession", on_delete=models.PROTECT, null=True, blank=True,
        related_name="cash_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("reference"), condition=Q(method="MPESA") & ~Q(reference=""),
                name="payment_mpesa_ref_ci_unique",
            ),
            models.CheckConstraint(
                condition=~Q(method="MPESA", reference=""),
                name="mpesa_transaction_requires_reference",
            ),
        ]

    @property
    def display_reference(self):
        if self.method != self.Method.MPESA or not self.reference:
            return ""
        return "••••" + self.reference[-4:] if len(self.reference) > 4 else "••••"

    def __str__(self):
        return f"{self.get_method_display()} {self.amount} ({self.get_status_display()})"


class SalePayment(models.Model):
    sale = models.ForeignKey("sales.Sale", related_name="payment_allocations", on_delete=models.PROTECT)
    payment_transaction = models.OneToOneField(PaymentTransaction, related_name="sale_allocation", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="sale_payment_amount_positive"),
        ]

    def clean(self):
        super().clean()
        if self.payment_transaction_id and self.amount is not None and self.amount > self.payment_transaction.amount:
            raise ValidationError({"amount": "Allocation cannot exceed its payment transaction."})

    @property
    def change_due(self):
        """Change returned for a cash tender; M-Pesa has no cash change."""
        if self.payment_transaction.method != PaymentTransaction.Method.CASH:
            return Decimal("0.00")
        return max(self.payment_transaction.amount - self.amount, Decimal("0.00"))

    def __str__(self):
        return f"{self.amount} allocated to Sale #{self.sale_id}"


class PaymentReconciliation(models.Model):
    class Decision(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        REJECTED = "REJECTED", "Rejected"

    payment_transaction = models.OneToOneField(PaymentTransaction, on_delete=models.PROTECT, related_name="reconciliation")
    decision = models.CharField(max_length=12, choices=Decision.choices)
    reference_snapshot = models.CharField(max_length=50)
    reason = models.TextField()
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reconciled_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Payment reconciliation records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Payment reconciliation records are immutable.")

    def __str__(self):
        return f"{self.decision} {self.reference_snapshot}"


class CashSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Awaiting manager approval"
        CLOSED = "CLOSED", "Closed"

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_sessions")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_cash_sessions")
    opening_float = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    opened_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    expected_cash = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    variance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    close_reason = models.TextField(blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="closed_cash_sessions")
    closed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_cash_sessions")
    approval_reason = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-opened_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(opening_float__gte=0), name="cash_session_float_nonnegative"),
            models.UniqueConstraint(fields=("cashier",), condition=models.Q(status__in=("OPEN", "PENDING_APPROVAL")), name="cash_session_one_active_per_cashier"),
        ]

    def __str__(self):
        return f"{self.cashier} · {self.opened_at:%Y-%m-%d %H:%M} · {self.get_status_display()}"


class CashSessionMovement(models.Model):
    class Type(models.TextChoices):
        EXPENSE = "EXPENSE", "Cash expense"
        CASH_IN = "CASH_IN", "Authorized cash in"
        CASH_OUT = "CASH_OUT", "Authorized cash out"

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_session_movements")
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0) | models.Q(amount__lt=0), name="cash_session_movement_nonzero")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Cash session movements are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Cash session movements are immutable.")

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.amount} · Session #{self.session_id}"


class RefundPayout(models.Model):
    refund = models.OneToOneField("sales.SaleRefund", on_delete=models.PROTECT, related_name="payout")
    method = models.CharField(max_length=10, choices=PaymentTransaction.Method.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=50, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="refund_payouts_issued")
    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, null=True, blank=True, related_name="refund_payouts")
    issued_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="refund_payout_amount_positive"),
            models.UniqueConstraint(Lower("reference"), condition=models.Q(method="MPESA") & ~models.Q(reference=""), name="refund_mpesa_ref_ci_unique"),
        ]

    @property
    def verification_status(self):
        if self.method == PaymentTransaction.Method.CASH:
            return "CONFIRMED"
        try:
            return self.payout_reconciliation.decision
        except PayoutReconciliation.DoesNotExist:
            return "UNVERIFIED"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Refund payout records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Refund payout records are immutable.")

    def __str__(self):
        return f"Refund payout {self.method} {self.amount}"


class PayoutReconciliation(models.Model):
    class Decision(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        REJECTED = "REJECTED", "Rejected"

    refund_payout = models.OneToOneField(RefundPayout, on_delete=models.PROTECT, null=True, blank=True, related_name="payout_reconciliation")
    commission_payout = models.OneToOneField("commissions.CommissionPayoutRecord", on_delete=models.PROTECT, null=True, blank=True, related_name="payout_reconciliation")
    decision = models.CharField(max_length=12, choices=Decision.choices)
    reference_snapshot = models.CharField(max_length=50)
    reason = models.TextField()
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payout_reconciliations")
    reconciled_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableManager()

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(refund_payout__isnull=False, commission_payout__isnull=True) | models.Q(refund_payout__isnull=True, commission_payout__isnull=False)), name="payout_reconciliation_exactly_one_target")]
        ordering = ("-reconciled_at", "-pk")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Payout reconciliation records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Payout reconciliation records are immutable.")

    def __str__(self):
        return f"{self.decision} M-Pesa payout · {self.reference_snapshot}"
