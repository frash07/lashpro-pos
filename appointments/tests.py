import uuid
from unittest.mock import patch
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
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

    def test_booking_date_input_renders_html5_iso_date(self):
        response = self.client.get(reverse("appointments:book"))
        self.assertEqual(response.status_code, 200)
        rendered_date = str(response.context["form"]["appointment_date"])
        self.assertIn(f'value="{timezone.localdate().isoformat()}"', rendered_date)

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

    def test_booking_page_explains_when_no_active_services_are_published(self):
        self.service.active = False
        self.service.save(update_fields=("active",))

        response = self.client.get(reverse("appointments:book"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Online booking is not available yet")
        self.assertContains(response, "has not published any active services")
        self.assertEqual(response.context["active_service_count"], 0)
        self.assertNotContains(response, 'name="service"')

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

    @override_settings(ALLOWED_HOSTS=["lashproke.cc", "pos.lashproke.cc"])
    def test_booking_page_and_availability_route_on_both_canonical_hosts(self):
        for host in ("lashproke.cc", "pos.lashproke.cc"):
            page = self.client.get(
                reverse("appointments:book"),
                {
                    "service": self.service.pk,
                    "appointment_date": self.day.isoformat(),
                },
                HTTP_HOST=host,
            )
            self.assertEqual(page.status_code, 200, host)
            self.assertContains(page, "Classic Lash Set")
            self.assertContains(page, "Nia Kamau")

            availability = self.client.get(
                reverse("appointments:availability"),
                {
                    "service": self.service.pk,
                    "date": self.day.isoformat(),
                },
                HTTP_HOST=host,
            )
            self.assertEqual(availability.status_code, 200, host)
            self.assertTrue(availability.json()["slots"])

    def test_guest_can_book_and_open_private_confirmation(self):
        slot = self._first_slot()
        response = self.client.post(reverse("appointments:book"), {
            "accept_terms": "on",
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


    @patch("appointments.views.send_booking_notification")
    def test_new_guest_booking_sends_request_received_notification(self, send_notification):
        slot = self._first_slot()
        response = self.client.post(reverse("appointments:book"), {
            "accept_terms": "on",
            "service": self.service.pk,
            "appointment_date": self.day.isoformat(),
            "slot": slot["value"],
            "full_name": "Guest Client",
            "email": "guest@example.com",
            "phone": "+254700123456",
            "notes": "",
            "idempotency_key": str(uuid.uuid4()),
        })

        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get()
        send_notification.assert_called_once_with(appointment, "REQUESTED")

    def test_appointment_request_requires_terms_acceptance(self):
        slot = self._first_slot()
        response = self.client.post(reverse("appointments:book"), {
            "service": self.service.pk,
            "appointment_date": self.day.isoformat(),
            "slot": slot["value"],
            "full_name": "Guest Client",
            "email": "guest@example.com",
            "phone": "+254 700 123 456",
            "notes": "",
            "idempotency_key": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertContains(response, "You must agree to the Terms of Service and Returns Policy")

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
