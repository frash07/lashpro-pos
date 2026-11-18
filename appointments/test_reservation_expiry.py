import uuid
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from catalog.models import Service
from appointments.models import Appointment, StaffAvailability
from appointments.services import create_appointment, expire_due_requested_appointments, get_available_slots


User = get_user_model()


class AppointmentHoldExpiryTests(TestCase):
    def setUp(self):
        self.provider = User.objects.create_user(
            username="expiry-tech", first_name="Nia", last_name="Kamau",
            password="StrongPassphrase!932", role=User.Role.TECHNICIAN, is_staff=True,
        )
        self.service = Service.objects.create(
            name="Expiry Classic Set", duration_minutes=60,
            price=Decimal("2500.00"), active=True,
        )
        self.day = timezone.localdate() + timedelta(days=2)
        StaffAvailability.objects.create(
            staff=self.provider, weekday=self.day.weekday(),
            start_time=time(9, 0), end_time=time(13, 0),
        )

    def _book(self, slot):
        return create_appointment(
            service=self.service, staff_id=slot["staff_id"], starts_at=slot["starts_at"],
            customer_name="Expiry Client", customer_email="expiry-client@example.com",
            customer_phone="+254700000002", idempotency_key=uuid.uuid4(),
        )

    def test_expired_request_is_marked_expired_and_provider_slot_is_reopened(self):
        slot = get_available_slots(service=self.service, day=self.day)[0]
        appointment = self._book(slot)
        appointment.expires_at = timezone.now() - timedelta(seconds=1)
        appointment.save(update_fields=("expires_at",))

        reopened = get_available_slots(service=self.service, day=self.day)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.EXPIRED)
        self.assertIsNotNone(appointment.expired_at)
        self.assertIn(slot["value"], [candidate["value"] for candidate in reopened])
        self.assertEqual(expire_due_requested_appointments(), 0)

    def test_confirmed_appointment_keeps_blocking_slot_after_request_hold_deadline(self):
        slot = get_available_slots(service=self.service, day=self.day)[0]
        appointment = self._book(slot)
        appointment.status = Appointment.Status.CONFIRMED
        appointment.expires_at = timezone.now() - timedelta(seconds=1)
        appointment.save(update_fields=("status", "expires_at", "updated_at"))

        self.assertEqual(expire_due_requested_appointments(), 0)
        remaining = get_available_slots(service=self.service, day=self.day)
        self.assertNotIn(slot["value"], [candidate["value"] for candidate in remaining])
        self.assertEqual(Appointment.objects.get(pk=appointment.pk).status, Appointment.Status.CONFIRMED)
