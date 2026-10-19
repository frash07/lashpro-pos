from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event

from .forms import (
    AssessmentForm,
    AssessmentResultForm,
    AttendanceForm,
    CohortForm,
    CertificateRevocationForm,
    CourseForm,
    EnrollmentForm,
    TrainingSessionForm,
)
from .models import Assessment, Attendance, Certificate, Cohort, Course, Enrollment, TrainingSession
from .services import (
    create_enrollment,
    create_assessment as create_assessment_record,
    create_training_session,
    issue_certificate,
    record_assessment_result,
    record_attendance,
    revoke_certificate,
    transition_cohort_status,
)

MANAGEMENT_ROLES = {User.Role.OWNER, User.Role.MANAGER}
ENROLLMENT_ROLES = MANAGEMENT_ROLES | {User.Role.CASHIER}


def _is_manager(user):
    return user.is_superuser or getattr(user, "role", None) in MANAGEMENT_ROLES


def _check_dashboard_access(user):
    if not user.is_active or not (user.is_superuser or user.role in MANAGEMENT_ROLES | {User.Role.TRAINER}):
        raise PermissionDenied


def _check_enrollment_access(user):
    if not user.is_active or not (user.is_superuser or user.role in ENROLLMENT_ROLES):
        raise PermissionDenied


def _get_visible_cohort(request, cohort_id):
    cohort = get_object_or_404(Cohort.objects.select_related("course", "trainer"), pk=cohort_id)
    if not _is_manager(request.user) and not (
        request.user.role == User.Role.TRAINER and cohort.trainer_id == request.user.pk
    ):
        raise PermissionDenied
    return cohort


def _add_validation_errors(form, exc):
    error_dict = getattr(exc, "error_dict", None)
    if error_dict:
        for field, errors in error_dict.items():
            target = field if field in form.fields else None
            for error in errors:
                form.add_error(target, error)
    else:
        form.add_error(None, exc)


def _flash_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


@login_required(login_url="login")
def dashboard(request):
    _check_dashboard_access(request.user)
    cohorts = Cohort.objects.select_related("course", "trainer").annotate(
        enrolled_count=Count(
            "enrollments",
            filter=~Q(enrollments__status=Enrollment.Status.WITHDRAWN),
            distinct=True,
        ),
    )
    if request.user.role == User.Role.TRAINER and not request.user.is_superuser:
        cohorts = cohorts.filter(trainer=request.user)
    cohorts = cohorts.order_by("-start_date", "course__name", "name")
    return render(request, "training/dashboard.html", {
        "cohorts": cohorts,
        "is_manager": _is_manager(request.user),
        "can_enroll": request.user.is_superuser or request.user.role in ENROLLMENT_ROLES,
    })


@login_required(login_url="login")
@transaction.atomic
def manage_catalog(request):
    if not _is_manager(request.user):
        raise PermissionDenied
    course_form = CourseForm(prefix="course")
    cohort_form = CohortForm(prefix="cohort")
    if request.method == "POST":
        if request.POST.get("form_type") == "course":
            course_form = CourseForm(request.POST, prefix="course")
            if course_form.is_valid():
                course = course_form.save()
                record_audit_event(
                    event_type=AuditEvent.EventType.APPROVAL,
                    object_type="training_course",
                    object_id=course.pk,
                    actor=request.user,
                    reason="Training course created.",
                    after_state={"code": course.code, "name": course.name, "tuition_fee": str(course.tuition_fee)},
                )
                messages.success(request, "Training course created.")
                return redirect("training:manage")
        elif request.POST.get("form_type") == "cohort":
            cohort_form = CohortForm(request.POST, prefix="cohort")
            if cohort_form.is_valid():
                cohort = cohort_form.save()
                record_audit_event(
                    event_type=AuditEvent.EventType.APPROVAL,
                    object_type="training_cohort",
                    object_id=cohort.pk,
                    actor=request.user,
                    reason="Training cohort created.",
                    after_state={"status": cohort.status, "start_date": str(cohort.start_date), "end_date": str(cohort.end_date)},
                    metadata={"course_id": cohort.course_id},
                )
                messages.success(request, "Training cohort created. Open it for enrollment when it is ready.")
                return redirect("training:manage")
        else:
            raise PermissionDenied
    courses = Course.objects.order_by("name", "pk")
    cohorts = Cohort.objects.select_related("course", "trainer").order_by("-start_date", "name")
    return render(request, "training/manage.html", {
        "course_form": course_form,
        "cohort_form": cohort_form,
        "courses": courses,
        "cohorts": cohorts,
    })


@login_required(login_url="login")
@transaction.atomic
def edit_course(request, course_id):
    if not _is_manager(request.user):
        raise PermissionDenied
    course = get_object_or_404(Course, pk=course_id)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        before = {"name": course.name, "tuition_fee": str(course.tuition_fee), "is_active": course.is_active}
        updated = form.save()
        record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="training_course",
            object_id=updated.pk,
            actor=request.user,
            reason="Training course details updated.",
            before_state=before,
            after_state={"name": updated.name, "tuition_fee": str(updated.tuition_fee), "is_active": updated.is_active},
        )
        messages.success(request, "Training course updated.")
        return redirect("training:manage")
    return render(request, "training/edit.html", {"form": form, "title": f"Edit {course.name}", "back_url": "training:manage"})


@login_required(login_url="login")
@transaction.atomic
def edit_cohort(request, cohort_id):
    if not _is_manager(request.user):
        raise PermissionDenied
    cohort = get_object_or_404(Cohort.objects.select_related("course"), pk=cohort_id)
    form = CohortForm(request.POST or None, instance=cohort)
    if request.method == "POST" and form.is_valid():
        before = {"course_id": cohort.course_id, "start_date": str(cohort.start_date), "end_date": str(cohort.end_date), "capacity": cohort.capacity}
        updated = form.save()
        record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="training_cohort",
            object_id=updated.pk,
            actor=request.user,
            reason="Training cohort details updated.",
            before_state=before,
            after_state={"course_id": updated.course_id, "start_date": str(updated.start_date), "end_date": str(updated.end_date), "capacity": updated.capacity},
        )
        messages.success(request, "Training cohort updated.")
        return redirect("training:manage")
    return render(request, "training/edit.html", {"form": form, "title": f"Edit {cohort.name}", "back_url": "training:manage"})


@login_required(login_url="login")
@require_POST
def change_cohort_status(request, cohort_id):
    cohort = get_object_or_404(Cohort, pk=cohort_id)
    try:
        transition_cohort_status(cohort=cohort, status=request.POST.get("status", ""), actor=request.user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    else:
        messages.success(request, "Cohort status updated.")
    return redirect("training:dashboard")


@login_required(login_url="login")
def enroll(request):
    _check_enrollment_access(request.user)
    if request.method == "POST":
        form = EnrollmentForm(request.POST)
        if form.is_valid():
            try:
                enrollment = create_enrollment(
                    cohort=form.cleaned_data["cohort"],
                    student=form.cleaned_data["student"],
                    student_name=form.cleaned_data["student_name"],
                    student_phone=form.cleaned_data["student_phone"],
                    actor=request.user,
                    idempotency_key=form.cleaned_data["idempotency_key"],
                )
            except ValidationError as exc:
                _add_validation_errors(form, exc)
            else:
                messages.success(
                    request,
                    f"Enrollment recorded for {enrollment.student.name}. Tuition invoice {enrollment.sale.receipt_number} is ready for collection.",
                )
                return redirect("sales:payments")
    else:
        form = EnrollmentForm()
    return render(request, "training/enroll.html", {"form": form})


@login_required(login_url="login")
def cohort_detail(request, cohort_id):
    _check_dashboard_access(request.user)
    cohort = _get_visible_cohort(request, cohort_id)
    enrollments = list(
        cohort.enrollments.exclude(status=Enrollment.Status.WITHDRAWN)
        .select_related("student", "sale")
        .prefetch_related("attendance__session", "assessment_results__assessment", "certificate")
        .order_by("student__name", "pk")
    )
    sessions = list(cohort.sessions.order_by("starts_at", "pk"))
    assessments = list(cohort.assessments.order_by("due_at", "title", "pk"))

    for session in sessions:
        session.roster_rows = []
        for enrollment in enrollments:
            attendance = next((row for row in enrollment.attendance.all() if row.session_id == session.pk), None)
            session.roster_rows.append({
                "enrollment": enrollment,
                "attendance": attendance,
                "form": AttendanceForm(initial={
                    "status": attendance.status if attendance else Attendance.Status.PRESENT,
                }),
            })

    for assessment in assessments:
        assessment.roster_rows = []
        for enrollment in enrollments:
            result = next((row for row in enrollment.assessment_results.all() if row.assessment_id == assessment.pk), None)
            assessment.roster_rows.append({
                "enrollment": enrollment,
                "result": result,
                "form": AssessmentResultForm(initial={
                    "score": result.score if result else "",
                    "feedback": result.feedback if result else "",
                }),
            })

    return render(request, "training/cohort_detail.html", {
        "cohort": cohort,
        "enrollments": enrollments,
        "sessions": sessions,
        "assessments": assessments,
        "session_form": TrainingSessionForm(),
        "assessment_form": AssessmentForm(),
        "is_manager": _is_manager(request.user),
        "now": timezone.now(),
    })


@login_required(login_url="login")
@require_POST
def create_session(request, cohort_id):
    cohort = _get_visible_cohort(request, cohort_id)
    form = TrainingSessionForm(request.POST)
    if form.is_valid():
        try:
            create_training_session(cohort=cohort, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, "Training session added.")
    else:
        _flash_form_errors(request, form)
    return redirect("training:cohort", cohort_id=cohort.pk)


@login_required(login_url="login")
@require_POST
def mark_attendance(request, session_id, enrollment_id):
    session = get_object_or_404(TrainingSession.objects.select_related("cohort"), pk=session_id)
    _get_visible_cohort(request, session.cohort_id)
    form = AttendanceForm(request.POST)
    if form.is_valid():
        try:
            record_attendance(
                session=session,
                enrollment=enrollment_id,
                status=form.cleaned_data["status"],
                actor=request.user,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, "Attendance saved.")
    else:
        messages.error(request, "Choose an attendance status.")
    return redirect("training:cohort", cohort_id=session.cohort_id)


@login_required(login_url="login")
@require_POST
def create_assessment(request, cohort_id):
    cohort = _get_visible_cohort(request, cohort_id)
    form = AssessmentForm(request.POST)
    if form.is_valid():
        try:
            assessment = create_assessment_record(cohort=cohort, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"Assessment '{assessment.title}' added.")
    else:
        _flash_form_errors(request, form)
    return redirect("training:cohort", cohort_id=cohort.pk)


@login_required(login_url="login")
@require_POST
def grade_assessment(request, assessment_id, enrollment_id):
    assessment = get_object_or_404(Assessment.objects.select_related("cohort"), pk=assessment_id)
    _get_visible_cohort(request, assessment.cohort_id)
    form = AssessmentResultForm(request.POST)
    if form.is_valid():
        try:
            record_assessment_result(
                assessment=assessment,
                enrollment=enrollment_id,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, "Assessment result saved.")
    else:
        _flash_form_errors(request, form)
    return redirect("training:cohort", cohort_id=assessment.cohort_id)


@login_required(login_url="login")
@require_POST
def issue_student_certificate(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment.objects.select_related("cohort"), pk=enrollment_id)
    _get_visible_cohort(request, enrollment.cohort_id)
    try:
        certificate = issue_certificate(enrollment=enrollment, actor=request.user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    else:
        messages.success(request, f"Certificate {certificate.certificate_number} is available.")
    return redirect("training:cohort", cohort_id=enrollment.cohort_id)


@login_required(login_url="login")
@require_POST
def revoke_student_certificate(request, certificate_id):
    if not _is_manager(request.user):
        raise PermissionDenied
    certificate = get_object_or_404(
        Certificate.objects.select_related("enrollment__cohort"),
        pk=certificate_id,
    )
    form = CertificateRevocationForm(request.POST)
    if form.is_valid():
        try:
            revoke_certificate(certificate=certificate, actor=request.user, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"Certificate {certificate.certificate_number} revoked.")
    else:
        messages.error(request, "Record a reason to revoke this certificate.")
    return redirect("training:cohort", cohort_id=certificate.enrollment.cohort_id)


@login_required(login_url="login")
def certificate_detail(request, certificate_id):
    certificate = get_object_or_404(
        Certificate.objects.select_related("enrollment__cohort__trainer"),
        pk=certificate_id,
    )
    cohort = certificate.enrollment.cohort
    if not _is_manager(request.user) and not (
        request.user.is_active
        and request.user.role == User.Role.TRAINER
        and cohort.trainer_id == request.user.pk
    ):
        raise PermissionDenied
    return render(request, "training/certificate.html", {"certificate": certificate})
