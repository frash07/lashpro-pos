import uuid

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from customers.models import Customer

from .models import Assessment, Attendance, Cohort, Course


class CustomerField(forms.ModelChoiceField):
    def label_from_instance(self, customer):
        if customer.phone:
            return f"{customer.name} · {customer.phone}"
        return customer.name


class CohortField(forms.ModelChoiceField):
    def label_from_instance(self, cohort):
        return (
            f"{cohort.course.name} · {cohort.name} · starts {cohort.start_date:%d %b %Y} · "
            f"KSh {cohort.tuition_fee:,.2f}"
        )


class EnrollmentForm(forms.Form):
    cohort = CohortField(queryset=Cohort.objects.none(), empty_label="Choose a cohort")
    student = CustomerField(queryset=Customer.objects.none(), required=False, empty_label="Choose an existing student")
    student_name = forms.CharField(required=False, max_length=100, label="New student's full name")
    student_phone = forms.CharField(required=False, max_length=20, label="New student's phone")
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("idempotency_key", uuid.uuid4())
        self.fields["cohort"].queryset = Cohort.objects.filter(
            status=Cohort.Status.ENROLLING,
            course__is_active=True,
            start_date__gte=timezone.localdate(),
        ).select_related("course").order_by("start_date", "course__name", "name")
        self.fields["student"].queryset = Customer.objects.order_by("name", "pk")

    def clean(self):
        data = super().clean()
        if not data:
            return data
        student_name = (data.get("student_name") or "").strip()
        student_phone = (data.get("student_phone") or "").strip()
        if data.get("student") and (student_name or student_phone):
            self.add_error("student_name", "Choose an existing student or enter a new student, not both.")
        elif not data.get("student") and not student_name:
            self.add_error("student_name", "Choose an existing student or enter the new student's name.")
        data["student_name"] = student_name
        data["student_phone"] = student_phone
        return data


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = (
            "code", "name", "description", "duration_days", "tuition_fee",
            "minimum_attendance_percent", "is_active",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class CohortForm(forms.ModelForm):
    class Meta:
        model = Cohort
        fields = (
            "course", "name", "trainer", "start_date", "end_date", "capacity",
            "tuition_fee_override",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(is_active=True)
        if self.instance.pk:
            courses = Course.objects.filter(Q(is_active=True) | Q(pk=self.instance.course_id))
        self.fields["course"].queryset = courses.order_by("name")
        self.fields["trainer"].queryset = User.objects.filter(
            role=User.Role.TRAINER, is_active=True
        ).order_by("first_name", "username")

    def clean(self):
        data = super().clean()
        capacity = data.get("capacity")
        if self.instance.pk and capacity is not None:
            enrolled = self.instance.enrollments.exclude(status="WITHDRAWN").count()
            if capacity < enrolled:
                self.add_error("capacity", f"Capacity cannot be less than the {enrolled} current enrollment(s).")
        if self.instance.pk and data.get("start_date") and data.get("end_date"):
            for session in self.instance.sessions.all():
                start = timezone.localtime(session.starts_at).date() if timezone.is_aware(session.starts_at) else session.starts_at.date()
                end = timezone.localtime(session.ends_at).date() if timezone.is_aware(session.ends_at) else session.ends_at.date()
                if start < data["start_date"] or end > data["end_date"]:
                    self.add_error("start_date", "Update or remove scheduled sessions before moving the cohort dates.")
                    break
        return data


class TrainingSessionForm(forms.Form):
    title = forms.CharField(max_length=120, label="Session topic")
    starts_at = forms.DateTimeField(
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    ends_at = forms.DateTimeField(
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    location = forms.CharField(max_length=160, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class AssessmentForm(forms.Form):
    title = forms.CharField(max_length=120)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    max_score = forms.DecimalField(min_value=0.01, max_digits=8, decimal_places=2, initial="100.00")
    passing_score = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2, initial="70.00")
    due_at = forms.DateTimeField(
        required=False,
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    def clean(self):
        data = super().clean()
        if data and data.get("max_score") is not None and data.get("passing_score") is not None:
            if data["passing_score"] > data["max_score"]:
                self.add_error("passing_score", "The passing score cannot exceed the maximum score.")
        return data


class AttendanceForm(forms.Form):
    status = forms.ChoiceField(choices=Attendance.Status.choices)


class AssessmentResultForm(forms.Form):
    score = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2)
    feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class CertificateRevocationForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
