from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html

from accounts.models import User
from .models import StorefrontOrder, StorefrontOrderLine, WhatsAppCatalogSync, WhatsAppInboundOrder
from .services import expire_due_storefront_orders, transition_storefront_order


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
        "reference", "source_channel", "customer_name", "customer_phone", "total_amount",
        "status", "pos_sale", "created_at", "expires_at",
    )
    list_filter = ("source_channel", "status", "created_at")
    search_fields = ("reference", "customer_name", "customer_email", "customer_phone", "sale__receipt_number")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = (StorefrontOrderLineInline,)
    actions = (
        "confirm_selected", "mark_ready_selected",
        "fulfil_selected", "cancel_selected",
    )
    fields = (
        "reference", "created_at", "updated_at", "expires_at", "expired_at",
        "source_channel", "external_order_id", "customer_name", "customer_email", "customer_phone", "notes",
        "payment_method", "total_amount", "status", "pos_sale_link",
    )
    readonly_fields = (
        "reference", "created_at", "updated_at", "expires_at", "expired_at",
        "source_channel", "external_order_id", "customer_name", "customer_email", "customer_phone", "notes",
        "payment_method", "total_amount", "status", "pos_sale_link",
    )

    def get_queryset(self, request):
        expire_due_storefront_orders(limit=500)
        return super().get_queryset(request).select_related("sale")

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

    @admin.display(description="POS sale", ordering="sale__receipt_number")
    def pos_sale(self, obj):
        if not obj.sale_id:
            return "Created when fulfilled"
        return obj.sale.receipt_number

    @admin.display(description="POS sale and payment")
    def pos_sale_link(self, obj):
        if not obj.sale_id:
            return "A POS sale is created when this order is fulfilled."
        receipt_url = reverse("sales:receipt", args=(obj.sale.receipt_token,))
        payments_url = reverse("sales:payments")
        return format_html(
            '<a href="{}">{}</a> · <a href="{}">Collect payment</a>',
            receipt_url,
            obj.sale.receipt_number,
            payments_url,
        )

    def _apply_transition(self, request, queryset, target_status, label):
        updated = 0
        failed = 0
        for order in queryset:
            try:
                transitioned = transition_storefront_order(
                    order=order,
                    target_status=target_status,
                    actor=request.user,
                )
                if transitioned.status != target_status:
                    failed += 1
                    self.message_user(
                        request,
                        f"{order.reference}: the unconfirmed reservation expired before this action; stock has been released.",
                        level=messages.ERROR,
                    )
                    continue
            except ValidationError as exc:
                failed += 1
                self.message_user(
                    request,
                    f"{order.reference}: {' '.join(exc.messages)}",
                    level=messages.ERROR,
                )
            else:
                updated += 1
        if updated:
            self.message_user(
                request,
                f"{updated} online order(s) {label}.",
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                f"{failed} order(s) could not be updated. Review the errors above.",
                level=messages.WARNING,
            )

    @admin.action(description="Confirm selected online orders")
    def confirm_selected(self, request, queryset):
        self._apply_transition(request, queryset, StorefrontOrder.Status.CONFIRMED, "confirmed")

    @admin.action(description="Mark selected orders ready for collection")
    def mark_ready_selected(self, request, queryset):
        self._apply_transition(request, queryset, StorefrontOrder.Status.READY, "marked ready")

    @admin.action(description="Fulfil orders, deduct stock and create POS sales")
    def fulfil_selected(self, request, queryset):
        self._apply_transition(request, queryset, StorefrontOrder.Status.FULFILLED, "fulfilled and posted to POS")

    @admin.action(description="Cancel selected orders and release reserved stock")
    def cancel_selected(self, request, queryset):
        self._apply_transition(request, queryset, StorefrontOrder.Status.CANCELLED, "cancelled")



@admin.register(WhatsAppInboundOrder)
class WhatsAppInboundOrderAdmin(admin.ModelAdmin):
    list_display = ("message_id", "customer_name", "sender_id", "status", "order", "received_at")
    list_filter = ("status", "received_at")
    search_fields = ("message_id", "customer_name", "sender_id", "issue", "order__reference")
    readonly_fields = (
        "message_id", "sender_id", "customer_name", "catalog_id", "status",
        "order", "issue", "received_at", "updated_at",
    )
    ordering = ("-received_at",)

    def has_module_permission(self, request):
        return StorefrontOrderAdmin._can_review(self, request)

    def has_view_permission(self, request, obj=None):
        return StorefrontOrderAdmin._can_review(self, request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WhatsAppCatalogSync)
class WhatsAppCatalogSyncAdmin(admin.ModelAdmin):
    list_display = (
        "retailer_id", "product", "status", "attempts", "last_synced_at", "updated_at"
    )
    list_filter = ("status",)
    search_fields = ("retailer_id", "product__name", "last_error")
    readonly_fields = (
        "product", "retailer_id", "status", "remote_product_id", "attempts",
        "last_error", "last_synced_at", "created_at", "updated_at",
    )
    actions = ("retry_selected_syncs",)

    def has_module_permission(self, request):
        return StorefrontOrderAdmin._can_review(self, request)

    def has_view_permission(self, request, obj=None):
        return StorefrontOrderAdmin._can_review(self, request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # All fields are read-only; change permission is enabled only so the
        # retry action is available to authorised staff.
        return StorefrontOrderAdmin._can_review(self, request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Retry selected WhatsApp catalogue syncs")
    def retry_selected_syncs(self, request, queryset):
        from .whatsapp import sync_catalog_record

        successes = failures = 0
        for record_id in queryset.values_list("pk", flat=True):
            try:
                record = sync_catalog_record(record_id)
            except Exception:
                failures += 1
                continue
            if record.status == WhatsAppCatalogSync.Status.SYNCED:
                successes += 1
            else:
                failures += 1
        if successes:
            self.message_user(request, f"{successes} catalogue item(s) synchronised.", level=messages.SUCCESS)
        if failures:
            self.message_user(request, f"{failures} catalogue item(s) still need attention.", level=messages.WARNING)
