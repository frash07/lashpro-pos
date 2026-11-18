import uuid
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User
from catalog.models import Service
from storefront.models import StorefrontProfile

from .forms import AppointmentBookingForm
from .models import Appointment
from .notifications import send_booking_notification
from .services import PROVIDER_ROLES, create_appointment, get_available_slots


CUSTOMER_ROLE = User.Role.CUSTOMER
BOOKING_WINDOW_DAYS = 60


def _customer_profile(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        profile = user.storefront_profile
    except StorefrontProfile.DoesNotExist:
        return None
    if user.role != CUSTOMER_ROLE:
        return None
    return profile


def _booking_initial(request):
    profile = _customer_profile(request.user)
    initial = {"appointment_date": timezone.localdate(), "idempotency_key": uuid.uuid4()}
    source = request.POST if request.method == "POST" else request.GET
    service_id = source.get("service")
    date_value = source.get("appointment_date")

    service = None
    try:
        if service_id:
            service = Service.objects.filter(pk=int(service_id), active=True).first()
    except (TypeError, ValueError):
        service = None

    if service:
        initial["service"] = service.pk

    if date_value:
        try:
            initial["appointment_date"] = date.fromisoformat(date_value)
        except (TypeError, ValueError):
            pass

    if profile:
        initial.update({
            "full_name": profile.customer.name,
            "email": profile.email,
            "phone": profile.customer.phone,
        })
    return initial, service


@never_cache
def book(request):
    initial, selected_service = _booking_initial(request)
    data = request.POST if request.method == "POST" else None
    form = AppointmentBookingForm(data=data, initial=initial)

    selected_date = initial["appointment_date"]
    today = timezone.localdate()
    if selected_service and today <= selected_date <= today + timedelta(days=BOOKING_WINDOW_DAYS):
        slots = get_available_slots(service=selected_service, day=selected_date)
    else:
        slots = []
    form.fields["slot"].choices = [("", "Choose an available time")] + [
        (slot["value"], slot["label"]) for slot in slots
    ]

    if request.method == "POST" and form.is_valid():
        staff_id_raw, starts_at_raw = form.cleaned_data["slot"].split("|", 1)
        try:
            starts_at = datetime.fromisoformat(starts_at_raw)
            if timezone.is_naive(starts_at):
                starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
            profile = _customer_profile(request.user)
            booking_key = form.cleaned_data["idempotency_key"]
            is_new_appointment = not Appointment.objects.filter(idempotency_key=booking_key).exists()
            appointment = create_appointment(
                service=form.cleaned_data["service"],
                staff_id=int(staff_id_raw),
                starts_at=starts_at,
                customer_name=form.cleaned_data["full_name"],
                customer_email=form.cleaned_data["email"],
                customer_phone=form.cleaned_data["phone"],
                notes=form.cleaned_data["notes"],
                account=request.user if profile else None,
                customer=profile.customer if profile else None,
                idempotency_key=booking_key,
            )
        except (ValueError, ValidationError) as exc:
            message = " ".join(exc.messages) if isinstance(exc, ValidationError) else "Choose a valid appointment time."
            form.add_error("slot", message)
            selected_service = form.cleaned_data["service"]
            slots = get_available_slots(
                service=selected_service,
                day=form.cleaned_data["appointment_date"],
            )
            form.fields["slot"].choices = [("", "Choose an available time")] + [
                (slot["value"], slot["label"]) for slot in slots
            ]
        else:
            messages.success(request, "Your appointment request has been received.")
            if is_new_appointment:
                send_booking_notification(appointment, "REQUESTED")
            return redirect("appointments:detail", token=appointment.access_token)

    context = {
        "form": form,
        "slots": slots,
        "selected_service": selected_service,
        "selected_date": selected_date,
        "active_service_count": Service.objects.filter(active=True).count(),
        "customer_account": _customer_profile(request.user),
    }
    return render(request, "appointments/book.html", context)


@require_GET
def availability(request):
    """JSON availability feed for booking widgets and external storefront clients."""
    try:
        service_id = int(request.GET.get("service", ""))
        selected_date = date.fromisoformat(request.GET.get("date", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Supply a valid service and date."}, status=400)

    today = timezone.localdate()
    if selected_date < today or selected_date > today + timedelta(days=BOOKING_WINDOW_DAYS):
        return JsonResponse({"error": "The requested date is outside the booking window."}, status=400)

    service = get_object_or_404(Service, pk=service_id, active=True)
    slots = get_available_slots(service=service, day=selected_date)
    return JsonResponse({
        "service": service.name,
        "date": selected_date.isoformat(),
        "slots": [{"value": slot["value"], "label": slot["label"]} for slot in slots],
    })


@never_cache
def detail(request, token):
    appointment = get_object_or_404(
        Appointment.objects.select_related("service", "staff"),
        access_token=token,
    )
    return render(request, "appointments/detail.html", {"appointment": appointment})


@login_required(login_url="storefront:login")
@never_cache
def account_appointments(request):
    profile = _customer_profile(request.user)
    if not profile:
        raise PermissionDenied
    appointments = Appointment.objects.filter(account=request.user).select_related("service", "staff")
    now = timezone.now()
    rows = [{
        "appointment": appointment,
        "can_cancel": (
            appointment.status in (Appointment.Status.REQUESTED, Appointment.Status.CONFIRMED)
            and (appointment.starts_at - now).total_seconds() >= 24 * 60 * 60
        ),
    } for appointment in appointments]
    return render(request, "appointments/account.html", {
        "appointment_rows": rows,
        "customer_account": profile,
    })


@login_required(login_url="storefront:login")
@require_POST
def cancel_appointment(request, pk):
    profile = _customer_profile(request.user)
    if not profile:
        raise PermissionDenied
    appointment = get_object_or_404(Appointment, pk=pk, account=request.user)
    hours_until_start = (appointment.starts_at - timezone.now()).total_seconds() / 3600
    if appointment.status not in (Appointment.Status.REQUESTED, Appointment.Status.CONFIRMED):
        messages.error(request, "This appointment can no longer be cancelled online.")
    elif hours_until_start < 24:
        messages.error(request, "Online cancellation closes 24 hours before the appointment. Please contact the studio.")
    else:
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=("status", "updated_at"))
        send_booking_notification(appointment, "CANCELLED")
        messages.success(request, "Your appointment has been cancelled.")
    return redirect("appointments:account")


def _staff_user(user):
    return user.is_authenticated and user.is_active and user.role in PROVIDER_ROLES


@login_required(login_url="login")
@never_cache
def staff_day(request):
    if not _staff_user(request.user):
        raise PermissionDenied
    try:
        selected_date = date.fromisoformat(request.GET.get("date", timezone.localdate().isoformat()))
    except (TypeError, ValueError):
        selected_date = timezone.localdate()

    appointments = Appointment.objects.filter(
        starts_at__date=selected_date,
    ).select_related("service", "staff").order_by("starts_at")
    if request.user.role not in (User.Role.OWNER, User.Role.MANAGER):
        appointments = appointments.filter(staff=request.user)

    return render(request, "appointments/staff_day.html", {
        "appointments": appointments,
        "selected_date": selected_date,
        "can_confirm": request.user.role in (User.Role.OWNER, User.Role.MANAGER),
    })


@login_required(login_url="login")
@require_POST
def update_status(request, pk):
    if not _staff_user(request.user):
        raise PermissionDenied
    appointment = get_object_or_404(Appointment, pk=pk)
    manager = request.user.role in (User.Role.OWNER, User.Role.MANAGER)
    if not manager and appointment.staff_id != request.user.pk:
        raise PermissionDenied

    requested_status = request.POST.get("status", "")
    allowed = {Appointment.Status.COMPLETED, Appointment.Status.NO_SHOW}
    if manager:
        allowed.update({Appointment.Status.CONFIRMED, Appointment.Status.CANCELLED})
    if requested_status not in allowed:
        raise PermissionDenied

    transitions = {
        Appointment.Status.REQUESTED: {
            Appointment.Status.CONFIRMED,
            Appointment.Status.CANCELLED,
            Appointment.Status.COMPLETED,
            Appointment.Status.NO_SHOW,
        },
        Appointment.Status.CONFIRMED: {
            Appointment.Status.CANCELLED,
            Appointment.Status.COMPLETED,
            Appointment.Status.NO_SHOW,
        },
    }
    if requested_status not in transitions.get(appointment.status, set()):
        messages.error(request, "That status change is not allowed.")
    else:
        previous_status = appointment.status
        appointment.status = requested_status
        appointment.save(update_fields=("status", "updated_at"))
        if previous_status != requested_status and requested_status in {
            Appointment.Status.CONFIRMED, Appointment.Status.CANCELLED
        }:
            send_booking_notification(appointment, requested_status)
        messages.success(request, f"Appointment {appointment.reference} updated.")
    return redirect(f"{reverse('appointments:staff-day')}?date={appointment.starts_at:%Y-%m-%d}")
