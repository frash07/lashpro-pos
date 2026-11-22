from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.core.exceptions import ValidationError


class Service(models.Model):
    class Kind(models.TextChoices):
        SERVICE = "SERVICE", "Service"
        TRAINING = "TRAINING", "Training"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SERVICE)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="catalog/", blank=True, null=True)
    commission_eligible = models.BooleanField(default=True)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.4000"),
        validators=[MinValueValidator(Decimal("0.0000")), MaxValueValidator(Decimal("1.0000"))],
    )
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(commission_rate__gte=0, commission_rate__lte=1),
                name="catalog_service_commission_rate_range",
            ),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="catalog/", blank=True, null=True)
    active = models.BooleanField(default=True)
    on_hand = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0.000"))],
    )
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0.000"))],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(on_hand__gte=0), name="catalog_product_stock_nonnegative"),
            models.CheckConstraint(condition=Q(reorder_level__gte=0), name="catalog_product_reorder_nonnegative"),
        ]

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self._state.adding:
            result = super().save(*args, **kwargs)
            try:
                SKUReservation.objects.create(sku=self.sku, product=self)
            except IntegrityError as exc:
                raise ValidationError({"sku": "This SKU has already been issued and cannot be reused."}) from exc
            return result

        previous_sku = type(self).objects.filter(pk=self.pk).values_list("sku", flat=True).first()
        if previous_sku is not None and previous_sku != self.sku:
            raise ValidationError({"sku": "A product SKU is permanent and cannot be changed."})
        result = super().save(*args, **kwargs)
        if previous_sku is not None:
            reservation = SKUReservation.objects.filter(sku=previous_sku).first()
            if reservation is None:
                SKUReservation.objects.create(sku=previous_sku, product=self)
            elif reservation.product_id != self.pk:
                raise ValidationError({"sku": "This SKU was issued to another product and cannot be reused."})
        return result

    @property
    def low_stock(self):
        return self.reorder_level > 0 and self.on_hand <= self.reorder_level

    def __str__(self):
        return self.name


class SKUReservationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("Issued SKUs are permanent and cannot be changed.")

    def delete(self):
        raise TypeError("Issued SKUs are permanent and cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("Issued SKUs are permanent and cannot be changed.")


class SKUReservation(models.Model):
    """Permanent record of every SKU ever assigned, even after product deletion."""

    sku = models.CharField(max_length=50, unique=True)
    product = models.OneToOneField(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sku_reservation",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = models.Manager.from_queryset(SKUReservationQuerySet)()

    class Meta:
        ordering = ("sku",)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise TypeError("Issued SKUs are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Issued SKUs are permanent and cannot be deleted.")

    def __str__(self):
        return self.sku




class WhatsAppCatalogSync(models.Model):
    """Maps one LashPro product to a Meta catalogue retailer ID and sync state."""

    class Status(models.TextChoices):
        UNLINKED = "UNLINKED", "Needs Meta catalogue mapping"
        PENDING = "PENDING", "Waiting to sync"
        SYNCING = "SYNCING", "Synchronising"
        SYNCED = "SYNCED", "Synchronised"
        FAILED = "FAILED", "Sync failed"

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="whatsapp_catalog_sync",
    )
    # Meta calls this the retailer_id / Content ID. Existing catalogue items
    # must be linked to their LashPro product before updates are enabled.
    retailer_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    meta_product_item_id = models.CharField(max_length=100, blank=True)
    catalog_linked = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNLINKED)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("product__name", "product__sku")

    def clean(self):
        super().clean()
        if self.catalog_linked and not (self.retailer_id or "").strip():
            raise ValidationError({"retailer_id": "Enter the matching Meta catalogue Content ID before enabling this link."})

    def __str__(self):
        return f"{self.product.sku} · {self.retailer_id or 'unlinked'}"
