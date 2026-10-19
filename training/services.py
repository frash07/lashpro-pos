from decimal import Decimal, InvalidOperation
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from sales.models import Sale, SaleLine

from .models import (
    Assessment,
    AssessmentResult,
    Attendance,
    Certificate,
    Cohort,
    Enrollment,
    TrainingSession,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
FINANCE_ROLES = {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}
TEACHING_ROLES = {User.Role.OWNER, User.Role.MANAGER}


def _is_manager(user):
    return bool(user and (user.is_superuser or getattr(user, "role", None) in TEACHING_ROLES))


def _can_teach_cohort(user, cohort):
    return _is_manager(user) or bool(
        user
        and user.is_active
        and getattr(user, "role", None) == User.Role.TRAINER
        and cohort.trainer_id == user.pk
    )


def _idempotency_key(value):
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise ValidationError({"idempotency_key": "Submit a valid enrollment form."}) from None


@transaction.atomic
def create_enrollment(*, cohort, student=None, student_name="", student_phone="", actor, idempotency_key):
    """Create a tuition invoice using a standard sale, ready for normal collection."""
    if not actor.is_active or not (actor.is_superuser or actor.role in FINANCE_ROLES):
        raise ValidationError({"actor": "Only an active owner, manager, or cashier can enroll a student."})

    key = _idempotency_key(idempotency_key)
    existing_sale = Sale.objects.filter(checkout_idempotency_key=key).first()
    if existing_sale:
        existing_enrollment = Enrollment.objects.filter(sale=existing_sale).first()
        if existing_enrollment and existing_sale.cashier_id == actor.pk:
            return existing_enrollment
        raise ValidationError({"idempotency_key": "This form key has already been used."})

    cohort_id = cohort.pk if isinstance(cohort, Cohort) else cohort
    try:
        locked_cohort = Cohort.objects.select_for_update().select_related("course").get(pk=cohort_id)
    except (Cohort.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"cohort": "Choose a valid training cohort."}) from None
    if not locked_cohort.course.is_active:
        raise ValidationError({"cohort": "This course is not currently available."})
    if locked_cohort.status != Cohort.Status.ENROLLING:
        raise ValidationError({"cohort": "This cohort is not open for enrollment."})
    if locked_cohort.start_date < timezone.localdate():
        raise ValidationError({"cohort": "Enrollment has closed because this cohort has started."})
    if locked_cohort.enrollments.exclude(status=Enrollment.Status.WITHDRAWN).count() >= locked_cohort.capacity:
        raise ValidationError({"cohort": "This cohort has reached capacity."})

    from customers.models import Customer
    if student:
        student_id = student.pk if hasattr(student, "pk") else student
        try:
            student = Customer.objects.get(pk=student_id)
        except (Customer.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"student": "Choose a valid LashPro customer record."}) from None
    else:
        student_name = (student_name or "").strip()
        student_phone = (student_phone or "").strip()
        if not student_name:
            raise ValidationError({"student_name": "Enter the student's full name."})
        existing_contact = Customer.objects.filter(phone=student_phone).first() if student_phone else None
        if existing_contact:
            if existing_contact.name.casefold() != student_name.casefold():
                raise ValidationError({"student_phone": "This phone number is already assigned to a different customer."})
            student = existing_contact
        else:
            student = Customer.objects.create(name=student_name, phone=student_phone)
    if locked_cohort.enrollments.filter(student=student).exclude(status=Enrollment.Status.WITHDRAWN).exists():
        raise ValidationError({"student": "This student already has an active enrollment in this cohort."})

    tuition_fee = locked_cohort.tuition_fee.quantize(CENT)
    try:
        with transaction.atomic():
            sale = Sale.objects.create(
                customer=student,
                cashier=actor,
                checkout_idempotency_key=key,
            )
            tuition_line = SaleLine.from_training_tuition(
                sale=sale,
                description=f"Training tuition: {locked_cohort.course.name} · {locked_cohort.name}",
                tuition_fee=tuition_fee,
            )
            tuition_line.full_clean()
            tuition_line.save()
            enrollment = Enrollment.objects.create(
                cohort=locked_cohort,
                student=student,
                sale=sale,
                tuition_fee=tuition_fee,
                status=Enrollment.Status.ENROLLED if tuition_fee == ZERO else Enrollment.Status.PENDING_PAYMENT,
            )
            sale.status = Sale.Status.COMPLETED
            sale.save(update_fields=("status",))
    except IntegrityError:
        existing_sale = Sale.objects.filter(checkout_idempotency_key=key).first()
        existing_enrollment = Enrollment.objects.filter(sale=existing_sale).first() if existing_sale else None
        if existing_enrollment and existing_sale.cashier_id == actor.pk:
            return existing_enrollment
        raise

    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_enrollment",
        object_id=enrollment.pk,
        actor=actor,
        reason="Training student enrolled and tuition invoice created.",
        after_state={"status": enrollment.status, "tuition_fee": str(tuition_fee)},
        metadata={
            "cohort_id": locked_cohort.pk,
            "student_id": student.pk,
            "sale_id": sale.pk,
            "receipt_number": sale.receipt_number,
        },
    )
    return enrollment


@transaction.atomic
def sync_enrollment_payment_status(enrollment):
    """Reflect net confirmed sale collections on an enrollment."""
    enrollment_id = enrollment.pk if isinstance(enrollment, Enrollment) else enrollment
    try:
        locked = Enrollment.objects.select_for_update().select_related("sale").get(pk=enrollment_id)
    except (Enrollment.DoesNotExist, TypeError, ValueError):
        return None
    if locked.status not in (Enrollment.Status.PENDING_PAYMENT, Enrollment.Status.ENROLLED):
        return locked
    target = (
        Enrollment.Status.ENROLLED
        if locked.sale.net_paid_amount >= locked.tuition_fee
        else Enrollment.Status.PENDING_PAYMENT
    )
    if locked.status != target:
        locked.status = target
        locked.save(update_fields=("status",))
    return locked


@transaction.atomic
def create_training_session(*, cohort, title, starts_at, ends_at, location="", notes="", actor):
    cohort_id = cohort.pk if isinstance(cohort, Cohort) else cohort
    try:
        locked_cohort = Cohort.objects.select_for_update().get(pk=cohort_id)
    except (Cohort.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"cohort": "Training cohort not found."}) from None
    if not _can_teach_cohort(actor, locked_cohort):
        raise ValidationError({"actor": "Only this cohort's trainer, an owner, or a manager can schedule sessions."})
    if locked_cohort.status in (Cohort.Status.COMPLETED, Cohort.Status.CANCELLED):
        raise ValidationError({"cohort": "Sessions cannot be added to a completed or cancelled cohort."})
    session = TrainingSession(
        cohort=locked_cohort,
        title=(title or "").strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        location=(location or "").strip(),
        notes=(notes or "").strip(),
        created_by=actor,
    )
    session.full_clean()
    session.save()
    return session


@transaction.atomic
def transition_cohort_status(*, cohort, status, actor):
    cohort_id = cohort.pk if isinstance(cohort, Cohort) else cohort
    try:
        locked = Cohort.objects.select_for_update().get(pk=cohort_id)
    except (Cohort.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"cohort": "Training cohort not found."}) from None
    if not _is_manager(actor):
        raise ValidationError({"actor": "Only an owner or manager can change cohort status."})
    try:
        status = Cohort.Status(str(status).upper())
    except ValueError:
        raise ValidationError({"status": "Choose a valid cohort status."}) from None
    transitions = {
        Cohort.Status.PLANNED: {Cohort.Status.ENROLLING, Cohort.Status.IN_PROGRESS, Cohort.Status.CANCELLED},
        Cohort.Status.ENROLLING: {Cohort.Status.IN_PROGRESS, Cohort.Status.CANCELLED},
        Cohort.Status.IN_PROGRESS: {Cohort.Status.COMPLETED, Cohort.Status.CANCELLED},
    }
    if status not in transitions.get(locked.status, set()):
        raise ValidationError({"status": "This cohort status change is not allowed."})
    today = timezone.localdate()
    if status == Cohort.Status.ENROLLING and locked.start_date < today:
        raise ValidationError({"status": "Enrollment cannot open after the cohort start date."})
    if status == Cohort.Status.IN_PROGRESS and today < locked.start_date:
        raise ValidationError({"status": "A cohort cannot start before its scheduled start date."})
    if status == Cohort.Status.COMPLETED and locked.end_date > today:
        raise ValidationError({"status": "A cohort cannot be completed before its scheduled end date."})
    before = locked.status
    locked.status = status
    locked.save(update_fields=("status", "updated_at"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_cohort",
        object_id=locked.pk,
        actor=actor,
        reason="Training cohort status changed.",
        before_state={"status": before},
        after_state={"status": locked.status},
        metadata={"course_id": locked.course_id},
    )
    return locked


@transaction.atomic
def create_assessment(*, cohort, title, description="", max_score, passing_score, due_at=None, actor):
    cohort_id = cohort.pk if isinstance(cohort, Cohort) else cohort
    try:
        locked_cohort = Cohort.objects.select_for_update().get(pk=cohort_id)
    except (Cohort.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"cohort": "Training cohort not found."}) from None
    if not _can_teach_cohort(actor, locked_cohort):
        raise ValidationError({"actor": "Only this cohort's trainer, an owner, or a manager can add assessments."})
    if locked_cohort.status in (Cohort.Status.COMPLETED, Cohort.Status.CANCELLED):
        raise ValidationError({"cohort": "Assessments cannot be added to a completed or cancelled cohort."})
    assessment = Assessment(
        cohort=locked_cohort,
        title=(title or "").strip(),
        description=(description or "").strip(),
        max_score=max_score,
        passing_score=passing_score,
        due_at=due_at,
        created_by=actor,
    )
    assessment.full_clean()
    assessment.save()
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_assessment",
        object_id=assessment.pk,
        actor=actor,
        reason="Training assessment created.",
        after_state={"title": assessment.title, "max_score": str(assessment.max_score), "passing_score": str(assessment.passing_score)},
        metadata={"cohort_id": locked_cohort.pk},
    )
    return assessment


@transaction.atomic
def record_attendance(*, session, enrollment, status, actor):
    session_id = session.pk if isinstance(session, TrainingSession) else session
    enrollment_id = enrollment.pk if isinstance(enrollment, Enrollment) else enrollment
    try:
        locked_session = TrainingSession.objects.select_for_update().select_related("cohort").get(pk=session_id)
        locked_enrollment = Enrollment.objects.select_for_update().select_related("cohort").get(pk=enrollment_id)
    except (TrainingSession.DoesNotExist, Enrollment.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"attendance": "Choose a valid session and student."}) from None
    if locked_session.cohort_id != locked_enrollment.cohort_id:
        raise ValidationError({"enrollment": "The student is not enrolled in this cohort."})
    if not _can_teach_cohort(actor, locked_session.cohort):
        raise ValidationError({"actor": "Only this cohort's trainer, an owner, or a manager can record attendance."})
    if locked_enrollment.status != Enrollment.Status.ENROLLED:
        raise ValidationError({"enrollment": "Attendance can be recorded for confirmed enrollments only."})
    if locked_session.ends_at > timezone.now():
        raise ValidationError({"session": "Attendance can be recorded after the session ends."})
    try:
        status = Attendance.Status(str(status).upper())
    except ValueError:
        raise ValidationError({"status": "Choose a valid attendance status."}) from None

    attendance, created = Attendance.objects.select_for_update().get_or_create(
        session=locked_session,
        enrollment=locked_enrollment,
        defaults={"status": status, "recorded_by": actor},
    )
    before = attendance.status if not created else None
    attendance.status = status
    attendance.recorded_by = actor
    attendance.full_clean()
    attendance.save()
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_attendance",
        object_id=attendance.pk,
        actor=actor,
        reason="Training attendance recorded.",
        before_state={"status": before} if before else {},
        after_state={"status": attendance.status},
        metadata={"session_id": locked_session.pk, "enrollment_id": locked_enrollment.pk},
    )
    return attendance


def _decimal_score(value):
    try:
        score = Decimal(str(value))
        rounded = score.quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"score": "Enter a valid score with up to two decimal places."}) from None
    if not score.is_finite() or score != rounded or score < ZERO:
        raise ValidationError({"score": "Enter a nonnegative score with up to two decimal places."})
    return rounded


@transaction.atomic
def record_assessment_result(*, assessment, enrollment, score, feedback="", actor):
    assessment_id = assessment.pk if isinstance(assessment, Assessment) else assessment
    enrollment_id = enrollment.pk if isinstance(enrollment, Enrollment) else enrollment
    try:
        locked_assessment = Assessment.objects.select_for_update().select_related("cohort").get(pk=assessment_id)
        locked_enrollment = Enrollment.objects.select_for_update().select_related("cohort").get(pk=enrollment_id)
    except (Assessment.DoesNotExist, Enrollment.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"assessment": "Choose a valid assessment and student."}) from None
    if locked_assessment.cohort_id != locked_enrollment.cohort_id:
        raise ValidationError({"enrollment": "The student is not enrolled in this assessment's cohort."})
    if not _can_teach_cohort(actor, locked_assessment.cohort):
        raise ValidationError({"actor": "Only this cohort's trainer, an owner, or a manager can grade students."})
    if locked_enrollment.status != Enrollment.Status.ENROLLED:
        raise ValidationError({"enrollment": "Only currently enrolled students can be graded."})
    score = _decimal_score(score)
    result, created = AssessmentResult.objects.select_for_update().get_or_create(
        assessment=locked_assessment,
        enrollment=locked_enrollment,
        defaults={"score": score, "feedback": (feedback or "").strip(), "graded_by": actor},
    )
    before = result.score if not created else None
    result.score = score
    result.feedback = (feedback or "").strip()
    result.graded_by = actor
    result.full_clean()
    result.save()
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_assessment_result",
        object_id=result.pk,
        actor=actor,
        reason="Training assessment graded.",
        before_state={"score": str(before)} if before is not None else {},
        after_state={"score": str(result.score), "passed": result.passed},
        metadata={"assessment_id": locked_assessment.pk, "enrollment_id": locked_enrollment.pk},
    )
    return result


@transaction.atomic
def issue_certificate(*, enrollment, actor):
    enrollment_id = enrollment.pk if isinstance(enrollment, Enrollment) else enrollment
    try:
        locked = Enrollment.objects.select_for_update().select_related(
            "sale", "student", "cohort__course", "cohort__trainer"
        ).get(pk=enrollment_id)
    except (Enrollment.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"enrollment": "Training enrollment not found."}) from None
    cohort = locked.cohort
    if not _can_teach_cohort(actor, cohort):
        raise ValidationError({"actor": "Only this cohort's trainer, an owner, or a manager can issue a certificate."})
    existing = Certificate.objects.filter(enrollment=locked).first()
    if existing:
        if existing.status == Certificate.Status.ISSUED:
            return existing
        raise ValidationError({"certificate": "A revoked certificate cannot be reissued for this enrollment."})
    if cohort.status != Cohort.Status.COMPLETED:
        raise ValidationError({"cohort": "Mark the cohort complete before issuing certificates."})
    if locked.status != Enrollment.Status.ENROLLED:
        raise ValidationError({"enrollment": "Only fully enrolled students can receive a certificate."})
    if locked.sale.net_paid_amount < locked.tuition_fee:
        raise ValidationError({"tuition": "Confirmed tuition must be fully paid before certification."})

    sessions = list(cohort.sessions.order_by("starts_at", "pk"))
    if not sessions:
        raise ValidationError({"attendance": "Schedule and record attendance for cohort sessions before certification."})
    attendance = {
        row.session_id: row
        for row in Attendance.objects.filter(enrollment=locked, session__cohort=cohort)
    }
    if any(session.ends_at > timezone.now() for session in sessions):
        raise ValidationError({"attendance": "The cohort still has a session that has not ended."})
    if any(session.pk not in attendance for session in sessions):
        raise ValidationError({"attendance": "Record attendance for every cohort session before certification."})
    countable = [row for row in attendance.values() if row.status != Attendance.Status.EXCUSED]
    attendance_rate = (
        Decimal(sum(row.status in (Attendance.Status.PRESENT, Attendance.Status.LATE) for row in countable))
        * Decimal("100.00") / Decimal(len(countable))
        if countable else ZERO
    )
    if attendance_rate < cohort.course.minimum_attendance_percent:
        raise ValidationError({"attendance": "The student's attendance is below the course certificate requirement."})

    assessments = list(cohort.assessments.order_by("pk"))
    results = {
        row.assessment_id: row
        for row in AssessmentResult.objects.filter(enrollment=locked, assessment__cohort=cohort)
    }
    if any(assessment.pk not in results for assessment in assessments):
        raise ValidationError({"assessment": "Grade every cohort assessment before certification."})
    if any(not results[assessment.pk].passed for assessment in assessments):
        raise ValidationError({"assessment": "The student must pass every cohort assessment before certification."})

    certificate = Certificate.objects.create(
        enrollment=locked,
        student_name=locked.student.name,
        course_name=cohort.course.name,
        cohort_name=cohort.name,
        issued_by=actor,
    )
    locked.status = Enrollment.Status.COMPLETED
    locked.save(update_fields=("status",))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_certificate",
        object_id=certificate.pk,
        actor=actor,
        reason="Training certificate issued after tuition, attendance, and assessment review.",
        after_state={"status": certificate.status, "certificate_number": certificate.certificate_number},
        metadata={"enrollment_id": locked.pk, "sale_id": locked.sale_id},
    )
    return certificate


@transaction.atomic
def revoke_certificate(*, certificate, actor, reason):
    if not actor.is_superuser and getattr(actor, "role", None) not in TEACHING_ROLES:
        raise ValidationError({"actor": "Only an owner or manager can revoke a certificate."})
    certificate_id = certificate.pk if isinstance(certificate, Certificate) else certificate
    try:
        locked = Certificate.objects.select_for_update().select_related("enrollment").get(pk=certificate_id)
    except (Certificate.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"certificate": "Certificate not found."}) from None
    reason = (reason or "").strip()
    if locked.status != Certificate.Status.ISSUED:
        raise ValidationError({"certificate": "This certificate has already been revoked."})
    if not reason:
        raise ValidationError({"reason": "Record why the certificate is being revoked."})
    locked.status = Certificate.Status.REVOKED
    locked.revoked_by = actor
    locked.revoked_at = timezone.now()
    locked.revocation_reason = reason
    locked.full_clean()
    locked.save(update_fields=("status", "revoked_by", "revoked_at", "revocation_reason"))
    record_audit_event(
        event_type=AuditEvent.EventType.APPROVAL,
        object_type="training_certificate",
        object_id=locked.pk,
        actor=actor,
        reason=reason,
        before_state={"status": Certificate.Status.ISSUED},
        after_state={"status": Certificate.Status.REVOKED},
        metadata={"certificate_number": locked.certificate_number, "enrollment_id": locked.enrollment_id},
    )
    return locked
