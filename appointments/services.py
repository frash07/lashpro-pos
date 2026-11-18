from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
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
NON_REQUEST_BOOKING_STATUSES = (
    Appointment.Status.CONFIRMED,
    Appointment.Status.COMPLETED,
    Appointment.Status.NO_SHOW,
)


def _expire_appointment_if_due(appointment_id, *, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        appointment = Appointment.objects.select_for_update().filter(pk=appointment_id).first()
        if (
            appointment is None
            or appointment.status != Appointment.Status.REQUESTED
            or appointment.expires_at > now
        ):
            return False
        appointment.status = Appointment.Status.EXPIRED
        appointment.expired_at = now
        appointment.save(update_fields=("status", "expired_at", "updated_at"))
        appointment_id = appointment.pk
        transaction.on_commit(lambda: _send_expiry_notification(appointment_id))
        return True


def _send_expiry_notification(appointment_id):
    from .notifications import send_booking_notification

    appointment = Appointment.objects.select_related("staff").filter(pk=appointment_id).first()
    if appointment:
        send_booking_notification(appointment, "EXPIRED")


def expire_due_requested_appointments(*, limit=500):
    """Expire public requests whose confirmation window has elapsed."""
    now = timezone.now()
    appointment_ids = list(
        Appointment.objects.filter(
            status=Appointment.Status.REQUESTED,
            expires_at__lte=now,
        ).order_by("expires_at", "pk").values_list("pk", flat=True)[:limit]
    )
    return sum(1 for appointment_id in appointment_ids if _expire_appointment_if_due(appointment_id, now=now))


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
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).filter(
        Q(status=Appointment.Status.REQUESTED, expires_at__gt=timezone.now())
        | Q(status__in=NON_REQUEST_BOOKING_STATUSES)
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

    # Materialise expired requests before building the public calendar.
    expire_due_requested_appointments(limit=500)

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
        expires_at=timezone.now() + timedelta(minutes=settings.PUBLIC_BOOKING_HOLD_MINUTES),
        idempotency_key=idempotency_key,
    )
