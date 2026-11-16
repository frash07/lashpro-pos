from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Appointment, StaffAvailability, StaffTimeOff


User = get_user_model()
PROVIDER_ROLES = ("OWNER", "MANAGER", "TECHNICIAN", "TRAINER")
SLOT_INTERVAL_MINUTES = 15
BOOKING_STATUSES = (
    Appointment.Status.REQUESTED,
    Appointment.Status.CONFIRMED,
    Appointment.Status.COMPLETED,
    Appointment.Status.NO_SHOW,
)


def _local_datetime(day, clock_time):
    return timezone.make_aware(
        datetime.combine(day, clock_time),
        timezone.get_current_timezone(),
    )


def _staff_display_name(staff):
    return staff.get_full_name().strip() or staff.username


def _slot_conflicts(*, staff, starts_at, ends_at, exclude_appointment_id=None):
    time_off = StaffTimeOff.objects.filter(
        staff=staff,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exists()
    if time_off:
        return True

    appointments = Appointment.objects.filter(
        staff=staff,
        status__in=BOOKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_appointment_id:
        appointments = appointments.exclude(pk=exclude_appointment_id)
    return appointments.exists()


def is_slot_available(*, service, staff, starts_at, exclude_appointment_id=None):
    """Validate one exact slot against the weekly schedule and dated exceptions."""
    if not service.active or service.duration_minutes < 1:
        return False
    if not staff.is_active or staff.role not in PROVIDER_ROLES:
        return False
    if timezone.is_naive(starts_at):
        return False

    starts_at = timezone.localtime(starts_at)
    if starts_at <= timezone.now():
        return False

    schedule = StaffAvailability.objects.filter(
        staff=staff,
        weekday=starts_at.weekday(),
        is_active=True,
    ).first()
    if not schedule:
        return False

    local_start = starts_at.time().replace(tzinfo=None, second=0, microsecond=0)
    minutes_from_open = (
        local_start.hour * 60 + local_start.minute
        - (schedule.start_time.hour * 60 + schedule.start_time.minute)
    )
    if minutes_from_open < 0 or minutes_from_open % SLOT_INTERVAL_MINUTES:
        return False

    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    schedule_end = _local_datetime(starts_at.date(), schedule.end_time)
    if ends_at > schedule_end:
        return False
    return not _slot_conflicts(
        staff=staff,
        starts_at=starts_at,
        ends_at=ends_at,
        exclude_appointment_id=exclude_appointment_id,
    )


def get_available_slots(*, service, day):
    """Return public booking choices, ordered by time then provider."""
    if not service or not service.active or service.duration_minutes < 1:
        return []

    schedules = StaffAvailability.objects.filter(
        weekday=day.weekday(),
        is_active=True,
        staff__is_active=True,
        staff__role__in=PROVIDER_ROLES,
    ).select_related("staff").order_by(
        "start_time", "staff__last_name", "staff__first_name", "staff__username"
    )

    slots = []
    now = timezone.now()
    for schedule in schedules:
        cursor = _local_datetime(day, schedule.start_time)
        closing = _local_datetime(day, schedule.end_time)
        duration = timedelta(minutes=service.duration_minutes)
        while cursor + duration <= closing:
            ends_at = cursor + duration
            if cursor > now and not _slot_conflicts(
                staff=schedule.staff,
                starts_at=cursor,
                ends_at=ends_at,
            ):
                slots.append({
                    "value": f"{schedule.staff_id}|{cursor.isoformat()}",
                    "label": f"{timezone.localtime(cursor):%I:%M %p} · {_staff_display_name(schedule.staff)}",
                    "staff_id": schedule.staff_id,
                    "starts_at": cursor,
                    "ends_at": ends_at,
                    "staff": schedule.staff,
                })
            cursor += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    return sorted(slots, key=lambda slot: (slot["starts_at"], slot["label"]))


@transaction.atomic
def create_appointment(
    *,
    service,
    staff_id,
    starts_at,
    customer_name,
    customer_email,
    customer_phone,
    notes="",
    account=None,
    customer=None,
    idempotency_key,
):
    """Create a booking while serialising requests for the selected provider."""
    existing = Appointment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    if timezone.is_naive(starts_at):
        raise ValidationError("Choose a valid appointment time.")

    try:
        staff = User.objects.select_for_update().get(
            pk=staff_id,
            is_active=True,
            role__in=PROVIDER_ROLES,
        )
    except User.DoesNotExist as exc:
        raise ValidationError("That provider is no longer available.") from exc

    # Locking the provider row serialises simultaneous bookings for that provider.
    # Recheck after acquiring the lock so concurrent requests cannot claim one slot.
    existing = Appointment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    starts_at = timezone.localtime(starts_at)
    if not is_slot_available(
        service=service,
        staff=staff,
        starts_at=starts_at,
    ):
        raise ValidationError("That appointment time has just become unavailable. Choose another time.")

    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    return Appointment.objects.create(
        service=service,
        staff=staff,
        customer=customer,
        account=account,
        service_name_snapshot=service.name,
        duration_minutes_snapshot=service.duration_minutes,
        price_snapshot=service.price,
        customer_name=customer_name.strip(),
        customer_email=customer_email.strip().lower(),
        customer_phone=customer_phone.strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        notes=(notes or "").strip(),
        idempotency_key=idempotency_key,
    )
