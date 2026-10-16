from django.contrib import admin
from .models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest


@admin.register(CommissionLedgerEntry)
class CommissionLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "entry_type", "technician", "sale_line", "base_amount", "rate_snapshot", "amount")
    list_filter = ("entry_type", "created_at")
    search_fields = ("technician__username", "sale_line__description")
    readonly_fields = tuple(field.name for field in CommissionLedgerEntry._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionledgerentry")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CommissionPayoutRequest)
class CommissionPayoutRequestAdmin(admin.ModelAdmin):
    list_display = ("requested_at", "technician", "amount", "method", "status", "requested_by", "reviewed_by")
    list_filter = ("status", "method", "requested_at")
    search_fields = ("technician__username", "reference", "reason")
    readonly_fields = tuple(field.name for field in CommissionPayoutRequest._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionpayoutrequest")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CommissionPayoutRecord)
class CommissionPayoutRecordAdmin(admin.ModelAdmin):
    list_display = ("issued_at", "technician", "amount", "method", "reference", "verification_status", "issued_by")
    list_filter = ("method", "issued_at")
    search_fields = ("technician__username", "reference")
    readonly_fields = tuple(field.name for field in CommissionPayoutRecord._meta.fields) + ("verification_status",)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("commissions.view_commissionpayoutrecord")
    def has_delete_permission(self, request, obj=None): return False
