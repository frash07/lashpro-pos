from django.contrib import admin

from accounts.models import User
from .models import StorefrontOrder, StorefrontOrderLine


STAFF_ROLES = {User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER}


class StorefrontOrderLineInline(admin.TabularInline):
    model = StorefrontOrderLine
    extra = 0
    can_delete = False
    fields = ("product", "sku_snapshot", "name_snapshot", "quantity", "unit_price", "line_total")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StorefrontOrder)
class StorefrontOrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "customer_name", "customer_phone", "total_amount",
        "status", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("reference", "customer_name", "customer_email", "customer_phone")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = (StorefrontOrderLineInline,)
    fields = (
        "reference", "created_at", "updated_at",
        "customer_name", "customer_email", "customer_phone", "notes",
        "payment_method", "total_amount", "status",
    )
    readonly_fields = (
        "reference", "created_at", "updated_at",
        "customer_name", "customer_email", "customer_phone", "notes",
        "payment_method", "total_amount",
    )

    def _can_review(self, request):
        user = request.user
        return user.is_active and user.is_staff and (
            user.is_superuser or getattr(user, "role", None) in STAFF_ROLES
        )

    def has_module_permission(self, request):
        return self._can_review(request)

    def has_view_permission(self, request, obj=None):
        return self._can_review(request)

    def has_change_permission(self, request, obj=None):
        return self._can_review(request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
