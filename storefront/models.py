import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from catalog.models import Product
from customers.models import Customer


def generate_order_reference():
    return "WEB-" + secrets.token_hex(4).upper()


def generate_order_token():
    return secrets.token_urlsafe(32)


def default_order_expiry():
    minutes = getattr(settings, "PUBLIC_ORDER_RESERVATION_MINUTES", 30)
    return timezone.now() + timedelta(minutes=minutes)


class StorefrontProfile(models.Model):
    """Links a public customer login to the existing POS customer record."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="storefront_profile",
    )
    customer = models.OneToOneField(
        Customer,
        on_delete=models.PROTECT,
        related_name="storefront_profile",
    )
    email = models.EmailField(max_length=254, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class StorefrontOrder(models.Model):
    class Status(models.TextChoices):
        PLACED = "PLACED", "Awaiting staff confirmation"
        CONFIRMED = "CONFIRMED", "Confirmed"
        READY = "READY", "Ready for collection"
        FULFILLED = "FULFILLED", "Fulfilled"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired — stock released"

    class PaymentMethod(models.TextChoices):
        PAY_AT_STUDIO = "PAY_AT_STUDIO", "Pay at studio"

    reference = models.CharField(
        max_length=20, unique=True, default=generate_order_reference, editable=False
    )
    access_token = models.CharField(
        max_length=64, unique=True, default=generate_order_token, editable=False
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="storefront_orders",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="storefront_orders",
    )
    sale = models.OneToOneField(
        "sales.Sale",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="storefront_order",
    )
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField(max_length=254)
    customer_phone = models.CharField(max_length=20)
    notes = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PLACED,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.PAY_AT_STUDIO,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    expires_at = models.DateTimeField(default=default_order_expiry, db_index=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return self.reference


class StorefrontOrderLine(models.Model):
    order = models.ForeignKey(
        StorefrontOrder,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="storefront_order_lines",
    )
    sku_snapshot = models.CharField(max_length=50)
    name_snapshot = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("pk",)
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="storefront_order_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(line_total__gte=0),
                name="storefront_order_line_total_nonnegative",
            ),
            models.UniqueConstraint(
                fields=("order", "product"),
                name="storefront_order_product_unique",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.name_snapshot}"



class StorefrontStockReservation(models.Model):
    """Quantity held for an online order until it is cancelled or fulfilled."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Reserved"
        CONSUMED = "CONSUMED", "Fulfilled"
        RELEASED = "RELEASED", "Released"

    order_line = models.OneToOneField(
        StorefrontOrderLine,
        on_delete=models.PROTECT,
        related_name="stock_reservation",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="storefront_stock_reservations",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="storefront_reservation_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.product} · {self.get_status_display()}"
