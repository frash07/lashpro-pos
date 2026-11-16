import uuid
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Service
from customers.models import Customer
from storefront.models import StorefrontProfile

from .models import Appointment, StaffAvailability, StaffTimeOff
from .services import create_appointment, get_available_slots


User = get_user_model()


class AppointmentBookingTests(TestCase):
    def setUp(self):
        self.provider = User.objects.create_user(
            username="lash-tech",
            first_name="Nia",
            last_name="Kamau",
            password="StrongPassphrase!932",
            role=User.Role.TECHNICIAN,
            is_staff=True,
        )
        self.service = Service.objects.create(
            name="Classic Lash Set",
            duration_minutes=60,
            price=Decimal("2500.00"),
            active=True,
        )
        self.day = timezone.localdate() + timedelta(days=2)
        StaffAvailability.objects.create(
            staff=self.provider,
            weekday=self.day.weekday(),
            start_time=time(9, 0),
            end_time=time(13, 0),
        )

    def _first_slot(self):
        slots = get_available_slots(service=self.service, day=self.day)
        self.assertTrue(slots)
        return slots[0]

    def _book(self, slot, key=None, **overrides):
        key = key or uuid.uuid4()
        return create_appointment(
            service=self.service,
            staff_id=slot["staff_id"],
            starts_at=slot["starts_at"],
            customer_name=overrides.get("customer_name", "Guest Client"),
            customer_email=overrides.get("customer_email", "guest@example.com"),
            customer_phone=overrides.get("customer_phone", "+254700000001"),
            notes=overrides.get("notes", ""),
            idempotency_key=key,
        )

    def test_public_page_lists_active_services_and_available_slots(self):
        response = self.client.get(reverse("appointments:book"), {
            "service": self.service.pk,
            "appointment_date": self.day.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classic Lash Set")
        self.assertContains(response, "Nia Kamau")
        self.assertContains(response, 'name="slot"')

    def test_availability_endpoint_returns_only_open_slots(self):
        response = self.client.get(reverse("appointments:availability"), {
            "service": self.service.pk,
            "date": self.day.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["service"], "Classic Lash Set")
        self.assertTrue(payload["slots"])
        self.assertIn("Nia Kamau", payload["slots"][0]["label"])

    def test_guest_can_book_and_open_private_confirmation(self):
        slot = self._first_slot()
        response = self.client.post(reverse("appointments:book"), {
            "service": self.service.pk,
            "appointment_date": self.day.isoformat(),
            "slot": slot["value"],
            "full_name": "Guest Client",
            "email": "GUEST@example.com",
            "phone": "+254 700 123 456",
            "notes": "Please call on arrival.",
            "idempotency_key": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get()
        self.assertIn(appointment.access_token, response.url)
        self.assertEqual(appointment.status, Appointment.Status.REQUESTED)
        self.assertEqual(appointment.customer_email, "guest@example.com")
        self.assertEqual(appointment.price_snapshot, Decimal("2500.00"))
        self.assertEqual(appointment.duration_minutes_snapshot, 60)
        self.assertIsNone(appointment.account)
        self.assertEqual(self.client.get(response.url).status_code, 200)

    def test_overlapping_booking_is_rejected_and_requested_booking_blocks_slots(self):
        slot = self._first_slot()
        self._book(slot)
        remaining = get_available_slots(service=self.service, day=self.day)
        self.assertNotIn(slot["value"], [candidate["value"] for candidate in remaining])
        with self.assertRaises(ValidationError):
            self._book(slot)

    def test_cancelled_appointment_releases_the_slot(self):
        slot = self._first_slot()
        appointment = self._book(slot)
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=("status", "updated_at"))
        self.assertIn(slot["value"], [candidate["value"] for candidate in get_available_slots(service=self.service, day=self.day)])

    def test_time_off_removes_overlapping_availability(self):
        slot = self._first_slot()
        StaffTimeOff.objects.create(
            staff=self.provider,
            starts_at=slot["starts_at"],
            ends_at=slot["ends_at"],
            reason="Personal leave",
        )
        self.assertNotIn(slot["value"], [candidate["value"] for candidate in get_available_slots(service=self.service, day=self.day)])

    def test_customer_can_view_and_cancel_appointment_from_account(self):
        user = User.objects.create_user(
            username="web-client",
            email="client@example.com",
            password="Client!SecurePassphrase932",
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(name="Client One", phone="+254711222333")
        StorefrontProfile.objects.create(user=user, customer=customer, email="client@example.com")
        slot = self._first_slot()
        appointment = self._book(slot)
        appointment.account = user
        appointment.customer = customer
        appointment.save(update_fields=("account", "customer"))

        self.client.force_login(user)
        response = self.client.get(reverse("appointments:account"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, appointment.reference)

        cancelled = self.client.post(reverse("appointments:cancel", args=[appointment.pk]))
        self.assertRedirects(cancelled, reverse("appointments:account"), fetch_redirect_response=False)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)

    def test_only_assigned_provider_can_open_staff_day_and_update_appointment(self):
        slot = self._first_slot()
        appointment = self._book(slot)
        self.client.force_login(self.provider)
        response = self.client.get(reverse("appointments:staff-day"), {"date": self.day.isoformat()})
        self.assertEqual(response.status_code, 200)
        updated = self.client.post(reverse("appointments:update-status", args=[appointment.pk]), {
            "status": Appointment.Status.COMPLETED,
        })
        self.assertRedirects(updated, f"{reverse('appointments:staff-day')}?date={self.day:%Y-%m-%d}", fetch_redirect_response=False)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_customer_role_cannot_access_staff_appointment_management(self):
        customer = User.objects.create_user(
            username="public-client",
            password="Client!SecurePassphrase932",
            role=User.Role.CUSTOMER,
            is_staff=False,
        )
        self.client.force_login(customer)
        response = self.client.get(reverse("appointments:staff-day"))
        self.assertEqual(response.status_code, 403)

    def test_booking_window_rejects_more_than_60_days(self):
        too_far = timezone.localdate() + timedelta(days=90)
        response = self.client.post(reverse("appointments:book"), {
            "service": self.service.pk,
            "appointment_date": too_far.isoformat(),
            "slot": "1|2027-01-01T09:00:00+03:00",
            "full_name": "Guest Client",
            "email": "guest@example.com",
            "phone": "+254700000001",
            "notes": "",
            "idempotency_key": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appointments can be booked up to 60 days ahead")

    def test_idempotency_key_returns_the_original_booking(self):
        slot = self._first_slot()
        key = uuid.uuid4()
        first = self._book(slot, key=key)
        second = self._book(slot, key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Appointment.objects.count(), 1)


class AppointmentModelConstraintTests(TestCase):
    def test_availability_rejects_end_before_start(self):
        provider = User.objects.create_user(
            username="invalid-provider",
            password="StrongPassphrase!932",
            role=User.Role.TECHNICIAN,
            is_staff=True,
        )
        availability = StaffAvailability(
            staff=provider,
            weekday=0,
            start_time=time(17, 0),
            end_time=time(9, 0),
        )
        with self.assertRaises(ValidationError):
            availability.full_clean()
