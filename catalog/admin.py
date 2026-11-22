from django.contrib import admin
from django.utils.html import format_html
from django.db.models import F, Q
from .models import Product, Service, WhatsAppCatalogSync


class LowStockFilter(admin.SimpleListFilter):
    title = "stock level"
    parameter_name = "stock_level"

    def lookups(self, request, model_admin):
        return (("low", "Low stock"), ("ok", "At or above reorder level"))

    def queryset(self, request, queryset):
        low = Q(on_hand__lte=F("reorder_level"), reorder_level__gt=0)
        if self.value() == "low":
            return queryset.filter(low)
        if self.value() == "ok":
            return queryset.exclude(low)
        return queryset


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "image_preview", "sku", "name", "selling_price",
        "on_hand", "reorder_level", "low_stock", "active",
    )
    list_filter = ("active", LowStockFilter)
    search_fields = ("sku", "name")
    change_form_template = "admin/catalog/product/change_form.html"
    fieldsets = (
        ("Product details", {"fields": (("sku", "name"), "image", "image_preview")}),
        ("Pricing", {"fields": (("cost_price", "selling_price"),)}),
        ("Inventory controls", {"fields": (("on_hand", "reorder_level"), "active")}),
    )

    @admin.display(description="Image preview")
    def image_preview(self, obj):
        if not obj or not obj.image:
            return "No image uploaded"
        return format_html(
            '<img src="{}" alt="{}" style="width:72px;height:72px;object-fit:cover;border-radius:10px;">',
            obj.image.url,
            obj.name,
        )

    def get_readonly_fields(self, request, obj=None):
        return ("on_hand", "sku", "image_preview") if obj else ("on_hand", "image_preview")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_minutes", "commission_eligible", "commission_rate", "active")
    list_filter = ("active", "commission_eligible")
    search_fields = ("name",)


@admin.register(WhatsAppCatalogSync)
class WhatsAppCatalogSyncAdmin(admin.ModelAdmin):
    list_display = (
        "product", "retailer_id", "catalog_linked", "status",
        "attempt_count", "last_synced_at", "updated_at",
    )
    list_filter = ("catalog_linked", "status")
    search_fields = ("product__sku", "product__name", "retailer_id", "meta_product_item_id")
    autocomplete_fields = ("product",)
    readonly_fields = ("meta_product_item_id", "status", "attempt_count", "next_attempt_at", "last_error", "last_synced_at", "updated_at")
    fields = (
        "product", "retailer_id", "catalog_linked", "meta_product_item_id",
        "status", "attempt_count", "next_attempt_at", "last_error",
        "last_synced_at", "updated_at",
    )

    def save_model(self, request, obj, form, change):
        obj.retailer_id = (obj.retailer_id or "").strip() or None
        if obj.catalog_linked:
            if not obj.retailer_id:
                from django.core.exceptions import ValidationError
                raise ValidationError("Enter the matching Meta catalogue Content ID before enabling this link.")
            from django.utils import timezone
            obj.status = WhatsAppCatalogSync.Status.PENDING
            obj.attempt_count = 0
            obj.next_attempt_at = timezone.now()
            obj.last_error = ""
        super().save_model(request, obj, form, change)
