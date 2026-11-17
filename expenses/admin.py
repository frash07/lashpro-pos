from django.contrib import admin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_date", "category", "description", "supplier", "amount", "payment_status", "payment_method", "created_by")
    list_filter = ("category", "payment_status", "payment_method", "expense_date")
    search_fields = ("description", "supplier", "reference")
    date_hierarchy = "expense_date"
    ordering = ("-expense_date", "-created_at")
    readonly_fields = tuple(field.name for field in Expense._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, "role", None) in {"OWNER", "MANAGER"}
