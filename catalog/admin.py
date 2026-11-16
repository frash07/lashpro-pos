from django.contrib import admin
from django.utils.html import format_html
from django.db.models import F, Q
from .models import Product, Service


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
