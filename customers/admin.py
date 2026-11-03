from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    change_list_template = "admin/customers/customer/change_list.html"
    list_display = ("name", "phone_display", "sales_count", "notes_preview")
    list_display_links = ("name",)
    search_fields = ("name", "phone", "notes")
    ordering = ("name",)
    list_per_page = 25

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(_sales_count=Count("sales", distinct=True))

    @admin.display(description="Phone", ordering="phone")
    def phone_display(self, obj):
        return obj.phone or "No phone added"

    @admin.display(description="Sales", ordering="_sales_count")
    def sales_count(self, obj):
        count = getattr(obj, "_sales_count", 0)
        if count:
            return format_html(
                '<span class="customer-sales-count has-sales">{}</span>',
                count,
            )
        return format_html(
            '<span class="customer-sales-count no-sales">No sales yet</span>'
        )

    @admin.display(description="Client notes")
    def notes_preview(self, obj):
        if not obj.notes:
            return "—"
        preview = Truncator(" ".join(obj.notes.split())).chars(72)
        return format_html('<span title="{}">{}</span>', obj.notes, preview)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and response.context_data:
            changelist = response.context_data.get("cl")
            if changelist is not None:
                queryset = changelist.queryset.order_by()
                response.context_data["customer_summary"] = {
                    "customer_count": queryset.values("pk").distinct().count(),
                    "with_phone": queryset.filter(phone__gt="").values("pk").distinct().count(),
                    "with_sales": queryset.filter(sales__isnull=False).values("pk").distinct().count(),
                    "with_notes": queryset.filter(notes__gt="").values("pk").distinct().count(),
                }
        return response
