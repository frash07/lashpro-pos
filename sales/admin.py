from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from accounts.models import User
from .models import Sale, SaleLine, SaleRefund, SaleRefundLine
from .services import issue_refund


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in SaleLine._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "customer", "cashier", "status", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = tuple(field.name for field in Sale._meta.fields)
    inlines = (SaleLineInline,)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SaleLine)
class SaleLineAdmin(admin.ModelAdmin):
    list_display = ("sale", "description", "service", "quantity", "technician", "service_completed_at")
    list_filter = ("service_completed_at",)
    search_fields = ("description", "sale__receipt_number", "technician__username")
    readonly_fields = tuple(field.name for field in SaleLine._meta.fields if field.name != "technician")
    actions = ("complete_services",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(service__isnull=False).select_related("sale", "service", "technician")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}

    @admin.action(description="Complete selected services and accrue commission")
    def complete_services(self, request, queryset):
        from commissions.services import complete_service_line
        for line in queryset:
            try:
                if not line.technician_id:
                    raise ValidationError("Assign a technician before completing the service.")
                complete_service_line(sale_line=line, technician=line.technician_id, actor=request.user)
            except ValidationError as exc:
                self.message_user(request, f"{line}: {exc.messages}", level=messages.ERROR)
        self.message_user(request, "Service completion review finished.")


class SaleRefundLineInline(admin.TabularInline):
    model = SaleRefundLine
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in SaleRefundLine._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SaleRefund)
class SaleRefundAdmin(admin.ModelAdmin):
    list_display = ("id", "sale", "amount", "method", "status", "requested_by", "reviewed_by", "requested_at")
    list_filter = ("status", "method", "requested_at")
    search_fields = ("sale__receipt_number", "reference", "reason")
    readonly_fields = tuple(field.name for field in SaleRefund._meta.fields)
    inlines = (SaleRefundLineInline,)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
