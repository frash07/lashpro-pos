import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class EnrollmentStatus(models.TextChoices):
    PENDING_PAYMENT = "PENDING_PAYMENT", "Awaiting confirmed tuition"
    ENROLLED = "ENROLLED", "Enrolled"
    COMPLETED = "COMPLETED", "Completed"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class Course(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    duration_days = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    tuition_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Default tuition in KSh. A cohort can set a different fee.",
    )
    minimum_attendance_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Required attendance for certificate eligibility. Excused sessions are excluded.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.CheckConstraint(condition=Q(duration_days__gt=0), name="training_course_duration_positive"),
            models.CheckConstraint(condition=Q(tuition_fee__gte=0), name="training_course_fee_nonnegative"),
            models.CheckConstraint(
                condition=Q(minimum_attendance_percent__gte=0, minimum_attendance_percent__lte=100),
                name="training_course_attendance_percent_range",
            ),
        ]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Cohort(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        ENROLLING = "ENROLLING", "Open for enrollment"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="cohorts")
    name = models.CharField(max_length=100)
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_cohorts",
        limit_choices_to={"role": "TRAINER", "is_active": True},
    )
    start_date = models.DateField()
    end_date = models.DateField()
    capacity = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1)])
    tuition_fee_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional cohort-specific tuition in KSh.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start_date", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("course", "name"), name="training_cohort_course_name_unique"),
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="training_cohort_dates_ordered"),
            models.CheckConstraint(condition=Q(capacity__gt=0), name="training_cohort_capacity_positive"),
            models.CheckConstraint(
                condition=Q(tuition_fee_override__isnull=True) | Q(tuition_fee_override__gte=0),
                name="training_cohort_fee_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The cohort end date must be on or after its start date."})
        if self.trainer_id and self.trainer.role != "TRAINER":
            raise ValidationError({"trainer": "Assign a staff account with the Trainer role."})

    @property
    def tuition_fee(self):
        return self.tuition_fee_override if self.tuition_fee_override is not None else self.course.tuition_fee

    @property
    def active_enrollment_count(self):
        return self.enrollments.exclude(status=EnrollmentStatus.WITHDRAWN).count()

    @property
    def available_seats(self):
        return max(self.capacity - self.active_enrollment_count, 0)

    def __str__(self):
        return f"{self.course.name} · {self.name}"


class Enrollment(models.Model):
    Status = EnrollmentStatus

    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name="enrollments")
    student = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="training_enrollments")
    sale = models.OneToOneField(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="training_enrollment",
    )
    tuition_fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    enrolled_at = models.DateTimeField(default=timezone.now)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("student__name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("cohort", "student"),
                condition=Q(status__in=(EnrollmentStatus.PENDING_PAYMENT, EnrollmentStatus.ENROLLED, EnrollmentStatus.COMPLETED)),
                name="training_active_student_cohort_unique",
            ),
            models.CheckConstraint(condition=Q(tuition_fee__gte=0), name="training_enrollment_fee_nonnegative"),
        ]

    @property
    def paid_amount(self):
        return self.sale.net_paid_amount

    @property
    def balance_due(self):
        return max(self.tuition_fee - self.paid_amount, 0)

    @property
    def attendance_percent(self):
        attendance = list(self.attendance.all())
        countable = [row for row in attendance if row.status != Attendance.Status.EXCUSED]
        if not countable:
            return 0
        attended = sum(row.status in (Attendance.Status.PRESENT, Attendance.Status.LATE) for row in countable)
        return round((attended / len(countable)) * 100, 2)

    def __str__(self):
        return f"{self.student.name} · {self.cohort}"


class TrainingSession(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name="sessions")
    title = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_training_sessions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("starts_at", "pk")
        constraints = [
            models.UniqueConstraint(fields=("cohort", "starts_at"), name="training_session_cohort_start_unique"),
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="training_session_dates_ordered"),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "The session must end after it starts."})
        if self.cohort_id and self.starts_at and self.ends_at:
            starts_date = timezone.localtime(self.starts_at).date() if timezone.is_aware(self.starts_at) else self.starts_at.date()
            ends_date = timezone.localtime(self.ends_at).date() if timezone.is_aware(self.ends_at) else self.ends_at.date()
            if starts_date < self.cohort.start_date or ends_date > self.cohort.end_date:
                raise ValidationError({"starts_at": "Schedule the session within the cohort dates."})

    def __str__(self):
        return f"{self.cohort} · {self.title} · {self.starts_at:%d %b %Y %H:%M}"


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        LATE = "LATE", "Late"
        ABSENT = "ABSENT", "Absent"
        EXCUSED = "EXCUSED", "Excused absence"

    session = models.ForeignKey(TrainingSession, on_delete=models.PROTECT, related_name="attendance")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="attendance")
    status = models.CharField(max_length=10, choices=Status.choices)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_training_attendance")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("enrollment__student__name", "pk")
        constraints = [models.UniqueConstraint(fields=("session", "enrollment"), name="training_session_student_attendance_unique")]

    def clean(self):
        super().clean()
        if self.session_id and self.enrollment_id and self.session.cohort_id != self.enrollment.cohort_id:
            raise ValidationError({"enrollment": "Attendance must use an enrollment from this session's cohort."})

    def __str__(self):
        return f"{self.enrollment.student.name} · {self.session.title} · {self.get_status_display()}"


class Assessment(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name="assessments")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    passing_score = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_training_assessments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("due_at", "title", "pk")
        constraints = [
            models.CheckConstraint(condition=Q(max_score__gt=0), name="training_assessment_max_score_positive"),
            models.CheckConstraint(condition=Q(passing_score__gte=0), name="training_assessment_pass_score_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if self.max_score is not None and self.max_score <= 0:
            raise ValidationError({"max_score": "The maximum score must be greater than zero."})
        if self.passing_score is not None and self.passing_score < 0:
            raise ValidationError({"passing_score": "The passing score cannot be negative."})
        if self.max_score is not None and self.passing_score is not None and self.passing_score > self.max_score:
            raise ValidationError({"passing_score": "The passing score cannot exceed the maximum score."})

    def __str__(self):
        return f"{self.cohort} · {self.title}"


class AssessmentResult(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="results")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="assessment_results")
    score = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="graded_training_assessments")
    graded_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("enrollment__student__name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("assessment", "enrollment"), name="training_assessment_student_result_unique"),
            models.CheckConstraint(condition=Q(score__gte=0), name="training_assessment_score_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if self.assessment_id and self.enrollment_id and self.assessment.cohort_id != self.enrollment.cohort_id:
            raise ValidationError({"enrollment": "The assessment and student must belong to the same cohort."})
        if self.assessment_id and self.score is not None and self.score > self.assessment.max_score:
            raise ValidationError({"score": "The score cannot exceed the assessment maximum."})

    @property
    def passed(self):
        return self.score >= self.assessment.passing_score

    def __str__(self):
        return f"{self.enrollment.student.name} · {self.assessment.title} · {self.score}/{self.assessment.max_score}"


def generate_certificate_number():
    return "LP-TC-" + secrets.token_hex(6).upper()


class Certificate(models.Model):
    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Issued"
        REVOKED = "REVOKED", "Revoked"

    enrollment = models.OneToOneField(Enrollment, on_delete=models.PROTECT, related_name="certificate")
    certificate_number = models.CharField(max_length=24, unique=True, default=generate_certificate_number, editable=False)
    student_name = models.CharField(max_length=120)
    course_name = models.CharField(max_length=120)
    cohort_name = models.CharField(max_length=100)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_training_certificates")
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="revoked_training_certificates")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-issued_at", "-pk")

    def clean(self):
        super().clean()
        if self.status == self.Status.REVOKED and not (self.revoked_by_id and self.revoked_at and self.revocation_reason.strip()):
            raise ValidationError("A revoked certificate requires a reviewer, time, and reason.")
        if self.status == self.Status.ISSUED and any((self.revoked_by_id, self.revoked_at, self.revocation_reason)):
            raise ValidationError("An issued certificate cannot have revocation details.")

    def __str__(self):
        return f"{self.certificate_number} · {self.student_name}"
