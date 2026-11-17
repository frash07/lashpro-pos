from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from audit.models import ImmutableManager


class Expense(models.Model):
    class Category(models.TextChoices):
        RENT = "RENT", "Rent"
        UTILITIES = "UTILITIES", "Utilities"
        SALON_SUPPLIES = "SALON_SUPPLIES", "Salon supplies"
        MARKETING = "MARKETING", "Marketing"
        TRANSPORT = "TRANSPORT", "Transport"
        MAINTENANCE = "MAINTENANCE", "Repairs and maintenance"
        STAFF = "STAFF", "Staff costs"
        INTERNET = "INTERNET", "Internet and communications"
        PROFESSIONAL = "PROFESSIONAL", "Professional fees"
        BANK_CHARGES = "BANK_CHARGES", "Bank charges"
        OTHER = "OTHER", "Other"

    class PaymentStatus(models.TextChoices):
        PAID = "PAID", "Paid"
        UNPAID = "UNPAID", "Unpaid"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        BANK = "BANK", "Bank transfer"

    expense_date = models.DateField(default=timezone.localdate)
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.CharField(max_length=500)
    supplier = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PAID)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    cash_session = models.ForeignKey("payments.CashSession", on_delete=models.PROTECT, null=True, blank=True, related_name="expenses")
    cash_movement = models.OneToOneField("payments.CashSessionMovement", on_delete=models.PROTECT, null=True, blank=True, related_name="expense_record")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableManager()

    class Meta:
        ordering = ("-expense_date", "-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive"),
            models.UniqueConstraint(
                Lower("reference"),
                condition=Q(payment_method="MPESA") & ~Q(reference=""),
                name="expense_mpesa_ref_ci_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("expense_date", "category"), name="expense_date_category_idx"),
            models.Index(fields=("payment_status", "expense_date"), name="expense_status_date_idx"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Expense amount must be greater than zero."
        if self.payment_status == self.PaymentStatus.UNPAID:
            if self.payment_method:
                errors["payment_method"] = "An unpaid expense must not have a payment method."
            if self.cash_session_id:
                errors["cash_session"] = "An unpaid expense cannot use a cash session."
            if self.reference:
                errors["reference"] = "An unpaid expense cannot have a payment reference."
        elif self.payment_status == self.PaymentStatus.PAID:
            if not self.payment_method:
                errors["payment_method"] = "Choose how the expense was paid."
            elif self.payment_method == self.PaymentMethod.CASH:
                if not self.cash_session_id:
                    errors["cash_session"] = "Select the open cash session used for this expense."
                elif self.cash_session.status != "OPEN":
                    errors["cash_session"] = "Cash expenses must be assigned to an open cash session."
            elif self.cash_session_id:
                errors["cash_session"] = "Only cash expenses can be assigned to a cash session."
            if self.payment_method == self.PaymentMethod.MPESA and not self.reference.strip():
                errors["reference"] = "Enter the M-Pesa transaction reference."
            if self.payment_method == self.PaymentMethod.CASH and not self.cash_movement_id:
                errors["cash_movement"] = "A cash-paid expense must link to its drawer movement."
            if self.payment_method != self.PaymentMethod.CASH and self.cash_movement_id:
                errors["cash_movement"] = "Only cash-paid expenses may link to a drawer movement."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            existing = type(self).objects.filter(pk=self.pk).first()
            if existing:
                immutable_fields = (
                    "expense_date", "category", "description", "supplier",
                    "amount", "created_by_id", "created_at",
                )
                if any(getattr(existing, field) != getattr(self, field) for field in immutable_fields):
                    raise TypeError("Expense details are immutable. Record a correcting entry instead.")
                if not (
                    existing.payment_status == self.PaymentStatus.UNPAID
                    and self.payment_status == self.PaymentStatus.PAID
                ):
                    raise TypeError("Only an unpaid expense may transition once to paid.")
                self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Expense records are immutable.")

    def __str__(self):
        return f"{self.get_category_display()} · KSh {self.amount} · {self.expense_date}"
