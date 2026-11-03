from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.utils.html import format_html

from .models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest


@admin.register(CommissionLedgerEntry)
class CommissionLedgerEntryAdmin(admin.ModelAdmin):
    change_list_template = "admin/commissions/commissionledgerentry/change_list.html"
    list_display = ("created_at", "entry_type", "technician", "sale_line", "base_amount", "rate_snapshot", "amount")
    list_filter = ("entry_type", "created_at")
    search_fields = ("technician__username", "sale_line__description")
    readonly_fields = tuple(field.name for field in CommissionLedgerEntry._meta.fields)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and response.context_data:
            changelist = response.context_data.get("cl")
            if changelist is not None:
                totals = changelist.queryset.aggregate(
                    entry_count=Count("pk"),
                    earned=Sum("amount", filter=Q(entry_type=CommissionLedgerEntry.Type.EARNED)),
                    reversals=Sum("amount", filter=Q(entry_type=CommissionLedgerEntry.Type.REVERSAL)),
                    net=Sum("amount"),
                )
                response.context_data["commission_summary"] = totals
        return response

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionledgerentry")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CommissionPayoutRequest)
class CommissionPayoutRequestAdmin(admin.ModelAdmin):
    change_list_template = "admin/commissions/commissionpayoutrequest/change_list.html"
    list_display = ("requested_at", "technician", "amount", "method", "status_badge", "requested_by", "reviewed_by")
    list_filter = ("status", "method", "requested_at")
    search_fields = ("technician__username", "requested_by__username", "reviewed_by__username", "reference", "reason")
    readonly_fields = tuple(field.name for field in CommissionPayoutRequest._meta.fields)

    @admin.display(description="Request status", ordering="status")
    def status_badge(self, obj):
        styles = {
            CommissionPayoutRequest.Status.REQUESTED: ("payout-status payout-status-pending", "Awaiting approval"),
            CommissionPayoutRequest.Status.ISSUED: ("payout-status payout-status-confirmed", "Issued"),
            CommissionPayoutRequest.Status.REJECTED: ("payout-status payout-status-rejected", "Rejected"),
        }
        css_class, label = styles.get(obj.status, ("payout-status", obj.get_status_display()))
        return format_html('<span class="{}">{}</span>', css_class, label)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and response.context_data:
            changelist = response.context_data.get("cl")
            if changelist is not None:
                response.context_data["payout_request_summary"] = changelist.queryset.aggregate(
                    request_count=Count("pk"),
                    awaiting_count=Count("pk", filter=Q(status=CommissionPayoutRequest.Status.REQUESTED)),
                    issued_count=Count("pk", filter=Q(status=CommissionPayoutRequest.Status.ISSUED)),
                    rejected_count=Count("pk", filter=Q(status=CommissionPayoutRequest.Status.REJECTED)),
                    awaiting_amount=Sum("amount", filter=Q(status=CommissionPayoutRequest.Status.REQUESTED)),
                    issued_amount=Sum("amount", filter=Q(status=CommissionPayoutRequest.Status.ISSUED)),
                    rejected_amount=Sum("amount", filter=Q(status=CommissionPayoutRequest.Status.REJECTED)),
                )
        return response

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionpayoutrequest")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CommissionPayoutRecord)
class CommissionPayoutRecordAdmin(admin.ModelAdmin):
    change_list_template = "admin/commissions/commissionpayoutrecord/change_list.html"
    list_display = ("issued_at", "technician", "amount", "method", "reference", "verification_badge", "issued_by")
    list_filter = ("method", "issued_at")
    search_fields = ("technician__username", "reference")
    readonly_fields = tuple(field.name for field in CommissionPayoutRecord._meta.fields) + ("verification_status",)

    @admin.display(description="Verification")
    def verification_badge(self, obj):
        status = obj.verification_status
        if status == "CONFIRMED":
            css_class, label = "payout-status payout-status-confirmed", "Confirmed"
        elif status == "REJECTED":
            css_class, label = "payout-status payout-status-rejected", "Rejected"
        else:
            css_class, label = "payout-status payout-status-pending", "Unverified"
        return format_html('<span class="{}">{}</span>', css_class, label)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and response.context_data:
            changelist = response.context_data.get("cl")
            if changelist is not None:
                totals = changelist.queryset.aggregate(
                    record_count=Count("pk"),
                    total_issued=Sum("amount"),
                    cash_total=Sum("amount", filter=Q(method=CommissionPayoutRequest.Method.CASH)),
                    mpesa_total=Sum("amount", filter=Q(method=CommissionPayoutRequest.Method.MPESA)),
                )
                response.context_data["payout_summary"] = totals
        return response

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionpayoutrecord")
    def has_delete_permission(self, request, obj=None): return False
