import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from catalog.models import Service


def generate_appointment_reference():
    return "APT-" + secrets.token_hex(4).upper()


def generate_appointment_token():
    return secrets.token_urlsafe(32)


def default_booking_expiry():
    minutes = getattr(settings, "PUBLIC_BOOKING_HOLD_MINUTES", 30)
    return timezone.now() + timedelta(minutes=minutes)


WEEKDAYS = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)


class StaffAvailability(models.Model):
    """A recurring weekly working window for one service provider."""

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appointment_availability",
    )
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("weekday", "start_time", "staff__last_name", "staff__first_name")
        constraints = [
            models.UniqueConstraint(
                fields=("staff", "weekday"),
                name="appt_staff_day_unique",
            ),
            models.CheckConstraint(
                condition=Q(start_time__lt=F("end_time")),
                name="appt_avail_time_order",
            ),
            models.CheckConstraint(
                condition=Q(weekday__gte=0, weekday__lte=6),
                name="appt_avail_day_range",
            ),
        ]

    def clean(self):
        super().clean()
        if self.staff_id and self.staff.role not in {
            "OWNER", "MANAGER", "TECHNICIAN", "TRAINER"
        }:
            raise ValidationError({"staff": "Choose an owner, manager, technician, or trainer."})
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({"end_time": "The end time must be after the start time."})

    def __str__(self):
        return f"{self.staff} · {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"


class StaffTimeOff(models.Model):
    """A dated block when a provider cannot accept appointments."""

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="appointment_time_off",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_appointment_time_off",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("starts_at", "staff__last_name")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="appt_timeoff_order",
            ),
        ]
        indexes = [
            models.Index(
                fields=("staff", "starts_at", "ends_at"),
                name="appt_timeoff_staff_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "The end time must be after the start time."})

    def __str__(self):
        return f"{self.staff} · unavailable {self.starts_at:%d %b %Y %H:%M}"


class Appointment(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Awaiting confirmation"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"
        NO_SHOW = "NO_SHOW", "No-show"
        EXPIRED = "EXPIRED", "Expired — slot released"

    reference = models.CharField(
        max_length=20,
        unique=True,
        default=generate_appointment_reference,
        editable=False,
    )
    access_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_appointment_token,
        editable=False,
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_appointments",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_appointments",
    )
    service_name_snapshot = models.CharField(max_length=100)
    duration_minutes_snapshot = models.PositiveIntegerField()
    price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField(max_length=254)
    customer_phone = models.CharField(max_length=20)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    notes = models.CharField(max_length=500, blank=True)
    expires_at = models.DateTimeField(default=default_booking_expiry, db_index=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("starts_at", "staff__last_name", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="appt_end_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=("staff", "starts_at", "ends_at"),
                name="appt_staff_start_idx",
            ),
            models.Index(
                fields=("status", "starts_at"),
                name="appt_status_start_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "The appointment end must be after its start."})

    def __str__(self):
        return f"{self.reference} · {self.service_name_snapshot}"
