from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from .models import InventoryMovement, ServiceConsumable, StockAdjustmentRequest
from .services import review_stock_adjustment


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "movement_type", "product", "quantity_delta", "actor", "sale_line")
    list_filter = ("movement_type", "created_at")
    search_fields = ("product__name", "product__sku", "reason")
    readonly_fields = tuple(field.name for field in InventoryMovement._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockAdjustmentRequest)
class StockAdjustmentRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "quantity_delta", "status", "requested_by", "reviewed_by")
    list_filter = ("status", "created_at")
    readonly_fields = ("requested_by", "status", "reviewed_by", "review_reason", "created_at", "reviewed_at")
    actions = ("approve_adjustments", "reject_adjustments")

    def save_model(self, request, obj, form, change):
        if not change and not obj.requested_by_id:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected stock adjustments")
    def approve_adjustments(self, request, queryset):
        self._review(request, queryset, True)

    @admin.action(description="Reject selected stock adjustments")
    def reject_adjustments(self, request, queryset):
        self._review(request, queryset, False)

    def _review(self, request, queryset, approve):
        for adjustment in queryset:
            try:
                review_stock_adjustment(adjustment=adjustment, approver=request.user, approve=approve)
            except ValidationError as exc:
                self.message_user(request, f"Adjustment #{adjustment.pk}: {exc.messages}", level=messages.ERROR)
        self.message_user(request, "Review completed.")


@admin.register(ServiceConsumable)
class ServiceConsumableAdmin(admin.ModelAdmin):
    list_display = ("service", "product", "quantity_per_service", "active")
    list_filter = ("active", "service")
    search_fields = ("service__name", "product__name", "product__sku")
