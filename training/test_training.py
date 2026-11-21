import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from commissions.models import CommissionLedgerEntry
from inventory.models import InventoryMovement
from payments.models import PaymentReconciliation, PaymentTransaction
from payments.services import reconcile_manual_mpesa
from sales.models import SaleLine
from sales.services import record_sale_payment

from .forms import CourseForm
from .models import (
    AssessmentResult,
    Attendance,
    Certificate,
    Cohort,
    Course,
    Enrollment,
)
from .services import (
    create_assessment,
    create_enrollment,
    create_training_session,
    issue_certificate,
    record_assessment_result,
    record_attendance,
    revoke_certificate,
    transition_cohort_status,
)


class TrainingServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.manager = User.objects.create_user(
            username="training-manager", password="test", role=User.Role.MANAGER
        )
        self.cashier = User.objects.create_user(
            username="training-cashier", password="test", role=User.Role.CASHIER
        )
        self.trainer = User.objects.create_user(
            username="training-trainer", password="test", role=User.Role.TRAINER
        )
        self.other_trainer = User.objects.create_user(
            username="other-training-trainer", password="test", role=User.Role.TRAINER
        )
        self.technician = User.objects.create_user(
            username="training-technician", password="test", role=User.Role.TECHNICIAN
        )

    def make_course(self, *, code="TC-01", name="Training Course", fee="1000.00", attendance="80"):
        return Course.objects.create(
            code=code,
            name=name,
            duration_days=10,
            tuition_fee=Decimal(fee),
            minimum_attendance_percent=Decimal(attendance),
        )

    def make_cohort(
        self,
        *,
        course=None,
        name="Cohort A",
        status=Cohort.Status.ENROLLING,
        start_date=None,
        end_date=None,
        capacity=4,
        trainer=None,
    ):
        course = course or self.make_course()
        return Cohort.objects.create(
            course=course,
            name=name,
            trainer=trainer or self.trainer,
            start_date=start_date or self.today + timedelta(days=2),
            end_date=end_date or self.today + timedelta(days=12),
            capacity=capacity,
            status=status,
        )

    def enroll(self, cohort, *, name="Student One", phone="0700000001", actor=None, key=None):
        return create_enrollment(
            cohort=cohort,
            student_name=name,
            student_phone=phone,
            actor=actor or self.cashier,
            idempotency_key=key or uuid.uuid4(),
        )

    def local_datetime(self, day, hour=9):
        return timezone.make_aware(datetime.combine(day, time(hour, 0)))

    def test_course_and_cohort_reject_invalid_values(self):
        form = CourseForm(
            {
                "code": "BAD-01",
                "name": "Invalid Course",
                "description": "",
                "duration_days": "0",
                "tuition_fee": "-1.00",
                "minimum_attendance_percent": "101",
                "is_active": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertTrue({"duration_days", "tuition_fee", "minimum_attendance_percent"} <= set(form.errors))

        course = self.make_course()
        invalid_cohort = Cohort(
            course=course,
            name="Invalid Cohort",
            trainer=self.technician,
            start_date=self.today + timedelta(days=4),
            end_date=self.today + timedelta(days=3),
            capacity=0,
        )
        with self.assertRaises(ValidationError):
            invalid_cohort.full_clean()

    def test_enrollment_creates_idempotent_tuition_only_invoice(self):
        cohort = self.make_cohort(capacity=3)
        key = uuid.uuid4()
        enrollment = self.enroll(cohort, key=key)
        retry = self.enroll(cohort, key=key)

        self.assertEqual(retry.pk, enrollment.pk)
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING_PAYMENT)
        self.assertEqual(enrollment.tuition_fee, Decimal("1000.00"))
        self.assertEqual(enrollment.sale.status, "COMPLETED")
        self.assertTrue(enrollment.sale.receipt_number)
        line = enrollment.sale.lines.get()
        self.assertEqual(line.line_type, SaleLine.LineType.TRAINING)
        self.assertIsNone(line.product_id)
        self.assertIsNone(line.service_id)
        self.assertEqual(line.line_total(), Decimal("1000.00"))
        self.assertFalse(InventoryMovement.objects.exists())
        self.assertFalse(CommissionLedgerEntry.objects.exists())

        with self.assertRaises(ValidationError):
            create_enrollment(
                cohort=cohort,
                student=enrollment.student,
                actor=self.cashier,
                idempotency_key=uuid.uuid4(),
            )
        with self.assertRaises(ValidationError):
            self.enroll(cohort, name="Different Student", phone="0700000001")

        cohort.capacity = 1
        cohort.save(update_fields=("capacity",))
        with self.assertRaises(ValidationError):
            self.enroll(cohort, name="Student Two", phone="0700000002")

    def test_unverified_mpesa_does_not_confirm_tuition_until_reconciled(self):
        cohort = self.make_cohort()
        enrollment = self.enroll(cohort)
        payment = record_sale_payment(
            sale=enrollment.sale,
            method=PaymentTransaction.Method.MPESA,
            amount="1000.00",
            reference="TRAINING-TEST-001",
            actor=self.cashier,
            idempotency_key=uuid.uuid4(),
        )
        enrollment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.UNVERIFIED)
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING_PAYMENT)

        reconciliation = reconcile_manual_mpesa(
            payment=payment,
            actor=self.manager,
            decision=PaymentReconciliation.Decision.CONFIRMED,
            reason="Matched to the test statement.",
        )
        enrollment.refresh_from_db()
        self.assertEqual(reconciliation.decision, PaymentReconciliation.Decision.CONFIRMED)
        self.assertEqual(
            PaymentTransaction.objects.get(pk=payment.pk).status,
            PaymentTransaction.Status.SUCCEEDED,
        )
        self.assertEqual(enrollment.status, Enrollment.Status.ENROLLED)

    def test_status_and_session_rules_enforce_dates_and_trainer_scope(self):
        planned = self.make_cohort(
            status=Cohort.Status.PLANNED,
            start_date=self.today + timedelta(days=4),
            end_date=self.today + timedelta(days=10),
        )
        with self.assertRaises(ValidationError):
            transition_cohort_status(cohort=planned, status=Cohort.Status.ENROLLING, actor=self.trainer)
        with self.assertRaises(ValidationError):
            transition_cohort_status(cohort=planned, status=Cohort.Status.COMPLETED, actor=self.manager)
        transition_cohort_status(cohort=planned, status=Cohort.Status.ENROLLING, actor=self.manager)
        with self.assertRaises(ValidationError):
            transition_cohort_status(cohort=planned, status=Cohort.Status.IN_PROGRESS, actor=self.manager)

        cohort = self.make_cohort(
            course=self.make_course(code="TC-02", name="Session Course", fee="0.00"),
            name="Session Cohort",
            status=Cohort.Status.ENROLLING,
            capacity=5,
        )
        enrollment = self.enroll(cohort)
        cohort.start_date = self.today - timedelta(days=3)
        cohort.end_date = self.today + timedelta(days=3)
        cohort.status = Cohort.Status.IN_PROGRESS
        cohort.save()

        with self.assertRaises(ValidationError):
            create_training_session(
                cohort=cohort,
                title="Unauthorized session",
                starts_at=self.local_datetime(self.today - timedelta(days=1)),
                ends_at=self.local_datetime(self.today - timedelta(days=1), 10),
                actor=self.other_trainer,
            )
        with self.assertRaises(ValidationError):
            create_training_session(
                cohort=cohort,
                title="Outside cohort",
                starts_at=self.local_datetime(self.today + timedelta(days=4)),
                ends_at=self.local_datetime(self.today + timedelta(days=4), 10),
                actor=self.trainer,
            )

        sessions = []
        for offset in (2, 1, 0):
            starts_at = timezone.now() - timedelta(days=offset + 1)
            sessions.append(
                create_training_session(
                    cohort=cohort,
                    title=f"Session {offset}",
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(hours=1),
                    actor=self.trainer,
                )
            )
        future_start = self.local_datetime(self.today + timedelta(days=1))
        future_session = create_training_session(
            cohort=cohort,
            title="Future session",
            starts_at=future_start,
            ends_at=future_start + timedelta(hours=1),
            actor=self.trainer,
        )
        with self.assertRaises(ValidationError):
            record_attendance(
                session=future_session,
                enrollment=enrollment,
                status=Attendance.Status.PRESENT,
                actor=self.trainer,
            )

        for session, status in zip(
            sessions,
            (Attendance.Status.PRESENT, Attendance.Status.ABSENT, Attendance.Status.EXCUSED),
        ):
            record_attendance(session=session, enrollment=enrollment, status=status, actor=self.trainer)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.attendance_percent, 50.0)

        unpaid_course = self.make_course(code="TC-03", name="Unpaid Course", fee="300.00")
        unpaid_cohort = self.make_cohort(course=unpaid_course, name="Unpaid Cohort")
        unpaid = self.enroll(unpaid_cohort, name="Unpaid Student", phone="0700000003")
        unpaid_cohort.start_date = self.today - timedelta(days=2)
        unpaid_cohort.end_date = self.today + timedelta(days=2)
        unpaid_cohort.status = Cohort.Status.IN_PROGRESS
        unpaid_cohort.save()
        starts_at = self.local_datetime(self.today - timedelta(days=1))
        past_session = create_training_session(
            cohort=unpaid_cohort,
            title="Past session",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            actor=self.trainer,
        )
        with self.assertRaises(ValidationError):
            record_attendance(
                session=past_session,
                enrollment=unpaid,
                status=Attendance.Status.PRESENT,
                actor=self.trainer,
            )

    def test_assessment_and_certificate_requirements_and_revoke(self):
        course = self.make_course(code="TC-04", name="Certificate Course", fee="0.00", attendance="80")
        cohort = self.make_cohort(course=course, name="Certificate Cohort")
        enrollment = self.enroll(cohort)
        cohort.start_date = self.today - timedelta(days=3)
        cohort.end_date = self.today - timedelta(days=1)
        cohort.status = Cohort.Status.IN_PROGRESS
        cohort.save()

        for offset in (2, 1):
            starts_at = self.local_datetime(self.today - timedelta(days=offset))
            create_training_session(
                cohort=cohort,
                title=f"Certificate Session {offset}",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                actor=self.trainer,
            )
        with self.assertRaises(ValidationError):
            create_assessment(
                cohort=cohort,
                title="Invalid assessment",
                max_score=100,
                passing_score=101,
                actor=self.trainer,
            )
        assessment = create_assessment(
            cohort=cohort,
            title="Practical assessment",
            max_score=100,
            passing_score=80,
            actor=self.trainer,
        )
        with self.assertRaises(ValidationError):
            issue_certificate(enrollment=enrollment, actor=self.trainer)
        transition_cohort_status(cohort=cohort, status=Cohort.Status.COMPLETED, actor=self.manager)
        with self.assertRaises(ValidationError):
            issue_certificate(enrollment=enrollment, actor=self.trainer)

        sessions = list(cohort.sessions.order_by("starts_at"))
        record_attendance(
            session=sessions[0], enrollment=enrollment, status=Attendance.Status.PRESENT, actor=self.trainer
        )
        record_attendance(
            session=sessions[1], enrollment=enrollment, status=Attendance.Status.ABSENT, actor=self.trainer
        )
        with self.assertRaises(ValidationError):
            issue_certificate(enrollment=enrollment, actor=self.trainer)
        record_attendance(
            session=sessions[1], enrollment=enrollment, status=Attendance.Status.PRESENT, actor=self.trainer
        )
        with self.assertRaises(ValidationError):
            issue_certificate(enrollment=enrollment, actor=self.trainer)
        with self.assertRaises(ValidationError):
            record_assessment_result(
                assessment=assessment, enrollment=enrollment, score=101, actor=self.trainer
            )
        result = record_assessment_result(
            assessment=assessment, enrollment=enrollment, score=90, actor=self.trainer
        )
        self.assertTrue(result.passed)
        self.assertEqual(AssessmentResult.objects.filter(assessment=assessment, enrollment=enrollment).count(), 1)

        certificate = issue_certificate(enrollment=enrollment, actor=self.trainer)
        enrollment.refresh_from_db()
        self.assertTrue(certificate.certificate_number.startswith("LP-TC-"))
        self.assertEqual(certificate.status, Certificate.Status.ISSUED)
        self.assertEqual(enrollment.status, Enrollment.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            revoke_certificate(certificate=certificate, actor=self.trainer, reason="Not authorized")
        revoked = revoke_certificate(certificate=certificate, actor=self.manager, reason="Test revocation")
        self.assertEqual(revoked.status, Certificate.Status.REVOKED)
        self.assertEqual(revoked.revocation_reason, "Test revocation")

    def test_certificate_is_blocked_until_confirmed_tuition_is_paid(self):
        course = self.make_course(code="TC-05", name="Tuition Gate Course", fee="100.00")
        cohort = self.make_cohort(course=course, name="Tuition Gate Cohort")
        enrollment = self.enroll(cohort)
        cohort.start_date = self.today - timedelta(days=2)
        cohort.end_date = self.today - timedelta(days=1)
        cohort.status = Cohort.Status.COMPLETED
        cohort.save()
        enrollment.status = Enrollment.Status.ENROLLED
        enrollment.save(update_fields=("status",))
        with self.assertRaisesMessage(ValidationError, "Confirmed tuition must be fully paid"):
            issue_certificate(enrollment=enrollment, actor=self.manager)
