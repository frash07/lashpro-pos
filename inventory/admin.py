from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    InventoryMovement,
    ServiceConsumable,
    StockAdjustmentRequest,
    StockReceipt,
    StockReceiptLine,
    Supplier,
)
from .services import request_stock_adjustment, review_stock_adjustment


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "contact_person", "phone", "email")
    ordering = ("name",)


class StockReceiptLineInline(admin.TabularInline):
    model = StockReceiptLine
    extra = 0
    can_delete = False
    fields = ("product", "quantity", "unit_cost")
    readonly_fields = fields
    show_change_link = False


@admin.register(StockReceipt)
class StockReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "received_date", "supplier", "reference_type", "supplier_reference",
        "line_count", "total_cost", "received_by",
    )
    list_filter = ("reference_type", "received_date", "supplier")
    search_fields = ("supplier__name", "supplier_reference", "delivery_note_number", "notes")
    readonly_fields = tuple(field.name for field in StockReceipt._meta.fields)
    inlines = (StockReceiptLineInline,)
    actions = None

    @admin.display(description="Lines")
    def line_count(self, obj):
        return obj.lines.count()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "movement_type", "product", "quantity_delta", "actor", "sale_line", "receipt_line")
    list_filter = ("movement_type", "created_at")
    search_fields = (
        "product__name", "product__sku", "reason",
        "receipt_line__receipt__supplier__name",
        "receipt_line__receipt__supplier_reference",
    )
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

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(field.name for field in obj._meta.fields)
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        created = request_stock_adjustment(
            product=obj.product,
            quantity_delta=obj.quantity_delta,
            reason=obj.reason,
            requested_by=request.user,
        )
        obj.__dict__.update(created.__dict__)

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
