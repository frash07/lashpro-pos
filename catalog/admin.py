from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, F, Q
from .models import Product, Service
from storefront.models import WhatsAppCatalogSync


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
        "image_preview", "sku", "whatsapp_retailer_id", "name", "selling_price",
        "on_hand", "reorder_level", "low_stock", "active",
    )
    list_display_links = ("image_preview", "name")
    list_filter = ("active", LowStockFilter)
    search_fields = ("sku", "whatsapp_retailer_id", "name")
    change_form_template = "admin/catalog/product/change_form.html"
    ordering = ("name", "pk")
    list_per_page = 48

    def changelist_view(self, request, extra_context=None):
        """Use Django's ChangeList for data/actions, never its markup for the workspace."""
        response = super().changelist_view(request, extra_context)
        context = getattr(response, "context_data", None)
        if not context or "cl" not in context:
            return response
        cl = context["cl"]
        if cl.is_popup:
            response.template_name = "admin/change_list.html"
            return response

        counts = cl.queryset.aggregate(
            active=Count("pk", filter=Q(active=True)),
            low=Count("pk", filter=Q(on_hand__lte=F("reorder_level"), reorder_level__gt=0)),
        )
        sort_fields = (
            ("name", "Name A–Z", "Name Z–A"),
            ("selling_price", "Price: low to high", "Price: high to low"),
            ("on_hand", "Stock: low to high", "Stock: high to low"),
            ("reorder_level", "Reorder: low to high", "Reorder: high to low"),
            ("sku", "SKU A–Z", "SKU Z–A"),
            ("whatsapp_retailer_id", "Meta ID A–Z", "Meta ID Z–A"),
            ("active", "Inactive first", "Active first"),
        )
        ordering = request.GET.get("o", "")
        sort_options = [("", "Default · name A–Z", not ordering)]
        for field, asc, desc in sort_fields:
            index = str(cl.list_display.index(field))
            sort_options.extend(((index, asc, ordering == index), ("-" + index, desc, ordering == "-" + index)))
        if ordering and not any(option[2] for option in sort_options):
            sort_options.append((ordering, "Current ordering", True))

        pages = []
        if cl.multi_page and not cl.show_all:
            for number in cl.paginator.get_elided_page_range(cl.page_num):
                if number == cl.paginator.ELLIPSIS:
                    pages.append({"ellipsis": True})
                else:
                    pages.append({
                        "number": number,
                        "current": number == cl.page_num,
                        "url": cl.get_query_string({"p": number}),
                    })
        context.update({
            "workspace_counts": counts,
            "workspace_filters": [
                {"title": spec.title, "choices": list(spec.choices(cl))}
                for spec in cl.filter_specs
            ],
            "workspace_search_params": [
                (key, value) for key, values in request.GET.lists()
                if key not in {"q", "o", "p", "all", "e"}
                for value in values
            ],
            "workspace_sorts": sort_options,
            "workspace_pages": pages,
            "workspace_previous": cl.get_query_string({"p": cl.page_num - 1}) if cl.multi_page and not cl.show_all and cl.page_num > 1 else "",
            "workspace_next": cl.get_query_string({"p": cl.page_num + 1}) if cl.multi_page and not cl.show_all and cl.page_num < cl.paginator.num_pages else "",
            "workspace_show_all": cl.get_query_string({"all": ""}, ["p"]) if cl.can_show_all and cl.multi_page and not cl.show_all else "",
            "workspace_facets": cl.get_query_string(remove=["_facets"]) if cl.add_facets else cl.get_query_string({"_facets": ""}),
        })
        return response

    fieldsets = (
        ("Product details", {"fields": (("sku", "name"), "image", "image_preview")}),
        ("Pricing", {"fields": (("cost_price", "selling_price"),)}),
        ("Sales channels", {"fields": ("whatsapp_retailer_id",)}),
        ("Inventory controls", {"fields": (("on_hand", "reorder_level"), "active")}),
    )

    @admin.display(description="Image preview")
    def image_preview(self, obj):
        if not obj or not obj.image:
            return "No image uploaded"
        return format_html(
            '<img src="{}" alt="{}" class="catalog-admin-thumbnail">',
            obj.image.url,
            obj.name,
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = ["on_hand", "image_preview"]
        if obj:
            readonly.append("sku")
            if WhatsAppCatalogSync.objects.filter(product=obj, remote_product_id__gt="").exists():
                readonly.append("whatsapp_retailer_id")
        return tuple(readonly)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_minutes", "commission_eligible", "commission_rate", "active")
    list_filter = ("active", "commission_eligible")
    search_fields = ("name",)
