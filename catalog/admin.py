from django.contrib import admin
from django.db.models import F
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


from django.db.models import Q


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "selling_price", "on_hand", "reorder_level", "low_stock", "active")
    list_filter = ("active", LowStockFilter)
    search_fields = ("sku", "name")
    def get_readonly_fields(self, request, obj=None):
        return ("on_hand", "sku") if obj else ("on_hand",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_minutes", "commission_eligible", "commission_rate", "active")
    list_filter = ("active", "commission_eligible")
    search_fields = ("name",)
