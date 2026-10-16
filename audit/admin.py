from django.contrib import admin
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "object_type", "object_id", "actor", "approver")
    list_filter = ("event_type", "created_at")
    search_fields = ("object_type", "object_id", "reason", "actor__username")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)
    ordering = ("-created_at",)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm("audit.view_auditevent")

    def has_delete_permission(self, request, obj=None):
        return False
