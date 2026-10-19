from django.contrib import admin

from .models import (
    Assessment,
    AssessmentResult,
    Attendance,
    Certificate,
    Cohort,
    Course,
    Enrollment,
    TrainingSession,
)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "duration_days", "tuition_fee", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "trainer", "start_date", "end_date", "capacity", "status")
    list_filter = ("status", "course", "start_date")
    search_fields = ("name", "course__name", "trainer__username", "trainer__first_name", "trainer__last_name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("course", "trainer")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "cohort", "status", "tuition_fee", "sale", "enrolled_at")
    list_filter = ("status", "cohort__course", "cohort")
    search_fields = ("student__name", "student__phone", "sale__receipt_number", "cohort__name")
    readonly_fields = tuple(field.name for field in Enrollment._meta.fields)
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in Attendance._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "cohort", "starts_at", "ends_at", "location")
    list_filter = ("cohort__course", "cohort", "starts_at")
    search_fields = ("title", "cohort__name", "cohort__course__name")
    readonly_fields = ("created_by", "created_at")
    inlines = (AttendanceInline,)
    autocomplete_fields = ("cohort", "created_by")


class AssessmentResultInline(admin.TabularInline):
    model = AssessmentResult
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in AssessmentResult._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("title", "cohort", "max_score", "passing_score", "due_at")
    list_filter = ("cohort__course", "cohort")
    search_fields = ("title", "cohort__name", "cohort__course__name")
    readonly_fields = ("created_by", "created_at")
    inlines = (AssessmentResultInline,)
    autocomplete_fields = ("cohort", "created_by")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("session", "enrollment", "status", "recorded_by", "updated_at")
    list_filter = ("status", "session__cohort__course", "session__cohort")
    search_fields = ("enrollment__student__name", "session__title", "session__cohort__name")
    readonly_fields = tuple(field.name for field in Attendance._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssessmentResult)
class AssessmentResultAdmin(admin.ModelAdmin):
    list_display = ("assessment", "enrollment", "score", "graded_by", "graded_at")
    list_filter = ("assessment__cohort__course", "assessment__cohort")
    search_fields = ("enrollment__student__name", "assessment__title")
    readonly_fields = tuple(field.name for field in AssessmentResult._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ("certificate_number", "student_name", "course_name", "cohort_name", "status", "issued_at")
    list_filter = ("status", "issued_at")
    search_fields = ("certificate_number", "student_name", "course_name", "cohort_name")
    readonly_fields = tuple(field.name for field in Certificate._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
