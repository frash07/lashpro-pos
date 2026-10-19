import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import training.models
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("customers", "0001_initial"),
        ("sales", "0008_training_tuition_lines"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Course",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=24, unique=True)),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("duration_days", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("tuition_fee", models.DecimalField(decimal_places=2, help_text="Default tuition in KSh. A cohort can set a different fee.", max_digits=10, validators=[django.core.validators.MinValueValidator(0)])),
                ("minimum_attendance_percent", models.DecimalField(decimal_places=2, default=80, help_text="Required attendance for certificate eligibility. Excused sessions are excluded.", max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name", "pk")},
        ),
        migrations.CreateModel(
            name="Cohort",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("capacity", models.PositiveSmallIntegerField(default=12, validators=[django.core.validators.MinValueValidator(1)])),
                ("tuition_fee_override", models.DecimalField(blank=True, decimal_places=2, help_text="Optional cohort-specific tuition in KSh.", max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("status", models.CharField(choices=[("PLANNED", "Planned"), ("ENROLLING", "Open for enrollment"), ("IN_PROGRESS", "In progress"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="PLANNED", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cohorts", to="training.course")),
                ("trainer", models.ForeignKey(blank=True, limit_choices_to={"is_active": True, "role": "TRAINER"}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="training_cohorts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-start_date", "name", "pk")},
        ),
        migrations.CreateModel(
            name="Enrollment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tuition_fee", models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(0)])),
                ("status", models.CharField(choices=[("PENDING_PAYMENT", "Awaiting confirmed tuition"), ("ENROLLED", "Enrolled"), ("COMPLETED", "Completed"), ("WITHDRAWN", "Withdrawn")], default="PENDING_PAYMENT", max_length=20)),
                ("enrolled_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawal_reason", models.TextField(blank=True)),
                ("cohort", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="enrollments", to="training.cohort")),
                ("sale", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="training_enrollment", to="sales.sale")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="training_enrollments", to="customers.customer")),
            ],
            options={"ordering": ("student__name", "pk")},
        ),
        migrations.CreateModel(
            name="TrainingSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("location", models.CharField(blank=True, max_length=160)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cohort", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sessions", to="training.cohort")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_training_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("starts_at", "pk")},
        ),
        migrations.CreateModel(
            name="Attendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PRESENT", "Present"), ("LATE", "Late"), ("ABSENT", "Absent"), ("EXCUSED", "Excused absence")], max_length=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("enrollment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attendance", to="training.enrollment")),
                ("recorded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recorded_training_attendance", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attendance", to="training.trainingsession")),
            ],
            options={"ordering": ("enrollment__student__name", "pk")},
        ),
        migrations.CreateModel(
            name="Assessment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("max_score", models.DecimalField(decimal_places=2, max_digits=8, validators=[django.core.validators.MinValueValidator(0)])),
                ("passing_score", models.DecimalField(decimal_places=2, max_digits=8, validators=[django.core.validators.MinValueValidator(0)])),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cohort", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assessments", to="training.cohort")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_training_assessments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("due_at", "title", "pk")},
        ),
        migrations.CreateModel(
            name="AssessmentResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("score", models.DecimalField(decimal_places=2, max_digits=8, validators=[django.core.validators.MinValueValidator(0)])),
                ("feedback", models.TextField(blank=True)),
                ("graded_at", models.DateTimeField(auto_now=True)),
                ("assessment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="results", to="training.assessment")),
                ("enrollment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assessment_results", to="training.enrollment")),
                ("graded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="graded_training_assessments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("enrollment__student__name", "pk")},
        ),
        migrations.CreateModel(
            name="Certificate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("certificate_number", models.CharField(default=training.models.generate_certificate_number, editable=False, max_length=24, unique=True)),
                ("student_name", models.CharField(max_length=120)),
                ("course_name", models.CharField(max_length=120)),
                ("cohort_name", models.CharField(max_length=100)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(choices=[("ISSUED", "Issued"), ("REVOKED", "Revoked")], default="ISSUED", max_length=10)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revocation_reason", models.TextField(blank=True)),
                ("enrollment", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="certificate", to="training.enrollment")),
                ("issued_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued_training_certificates", to=settings.AUTH_USER_MODEL)),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="revoked_training_certificates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-issued_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="course",
            constraint=models.CheckConstraint(condition=Q(duration_days__gt=0), name="training_course_duration_positive"),
        ),
        migrations.AddConstraint(
            model_name="course",
            constraint=models.CheckConstraint(condition=Q(tuition_fee__gte=0), name="training_course_fee_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="course",
            constraint=models.CheckConstraint(condition=Q(minimum_attendance_percent__gte=0, minimum_attendance_percent__lte=100), name="training_course_attendance_percent_range"),
        ),
        migrations.AddConstraint(
            model_name="cohort",
            constraint=models.UniqueConstraint(fields=("course", "name"), name="training_cohort_course_name_unique"),
        ),
        migrations.AddConstraint(
            model_name="cohort",
            constraint=models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="training_cohort_dates_ordered"),
        ),
        migrations.AddConstraint(
            model_name="cohort",
            constraint=models.CheckConstraint(condition=Q(capacity__gt=0), name="training_cohort_capacity_positive"),
        ),
        migrations.AddConstraint(
            model_name="cohort",
            constraint=models.CheckConstraint(condition=Q(tuition_fee_override__isnull=True) | Q(tuition_fee_override__gte=0), name="training_cohort_fee_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="enrollment",
            constraint=models.UniqueConstraint(fields=("cohort", "student"), condition=Q(status__in=("PENDING_PAYMENT", "ENROLLED", "COMPLETED")), name="training_active_student_cohort_unique"),
        ),
        migrations.AddConstraint(
            model_name="enrollment",
            constraint=models.CheckConstraint(condition=Q(tuition_fee__gte=0), name="training_enrollment_fee_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="trainingsession",
            constraint=models.UniqueConstraint(fields=("cohort", "starts_at"), name="training_session_cohort_start_unique"),
        ),
        migrations.AddConstraint(
            model_name="trainingsession",
            constraint=models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="training_session_dates_ordered"),
        ),
        migrations.AddConstraint(
            model_name="attendance",
            constraint=models.UniqueConstraint(fields=("session", "enrollment"), name="training_session_student_attendance_unique"),
        ),
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(condition=Q(max_score__gt=0), name="training_assessment_max_score_positive"),
        ),
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(condition=Q(passing_score__gte=0), name="training_assessment_pass_score_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="assessmentresult",
            constraint=models.UniqueConstraint(fields=("assessment", "enrollment"), name="training_assessment_student_result_unique"),
        ),
        migrations.AddConstraint(
            model_name="assessmentresult",
            constraint=models.CheckConstraint(condition=Q(score__gte=0), name="training_assessment_score_nonnegative"),
        ),
    ]
