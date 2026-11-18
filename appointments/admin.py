from django.contrib import admin

from .models import Appointment, StaffAvailability, StaffTimeOff
from .services import expire_due_requested_appointments


@admin.register(StaffAvailability)
class StaffAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("staff", "weekday", "start_time", "end_time", "is_active")
    list_filter = ("weekday", "is_active", "staff__role")
    search_fields = ("staff__username", "staff__first_name", "staff__last_name")
    ordering = ("weekday", "start_time")


@admin.register(StaffTimeOff)
class StaffTimeOffAdmin(admin.ModelAdmin):
    list_display = ("staff", "starts_at", "ends_at", "reason", "created_by")
    list_filter = ("staff__role",)
    search_fields = ("staff__username", "staff__first_name", "staff__last_name", "reason")
    readonly_fields = ("created_at",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "starts_at", "service_name_snapshot", "staff",
        "customer_name", "customer_phone", "status", "expires_at",
    )
    list_filter = ("status", "starts_at", "staff")
    search_fields = (
        "reference", "customer_name", "customer_email", "customer_phone",
        "service_name_snapshot", "staff__username", "staff__first_name", "staff__last_name",
    )
    date_hierarchy = "starts_at"
    list_select_related = ("service", "staff", "customer", "account")
    readonly_fields = (
        "reference", "access_token", "idempotency_key", "service", "staff",
        "customer", "account", "service_name_snapshot", "duration_minutes_snapshot",
        "price_snapshot", "customer_name", "customer_email", "customer_phone",
        "starts_at", "ends_at", "notes", "expires_at", "expired_at", "created_at", "updated_at",
    )
    fields = (
        "reference", "status", "service", "staff", "customer", "account",
        "service_name_snapshot", "duration_minutes_snapshot", "price_snapshot",
        "customer_name", "customer_email", "customer_phone", "starts_at", "ends_at",
        "notes", "expires_at", "expired_at", "access_token", "idempotency_key", "created_at", "updated_at",
    )
