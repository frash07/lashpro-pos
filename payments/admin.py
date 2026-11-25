from django.contrib import admin
from .models import (
    CashSession, CashSessionMovement, PaymentReconciliation, PaymentTransaction,
    MpesaC2BPayment, MpesaStkPush, PayoutReconciliation, RefundPayout, SalePayment,
)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "method", "status", "amount", "reference", "cash_session", "created_at")
    list_filter = ("method", "status", "created_at")
    search_fields = ("reference",)
    readonly_fields = tuple(field.name for field in PaymentTransaction._meta.fields)
    actions = None
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(SalePayment)
class SalePaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "sale", "payment_transaction", "amount", "created_at")
    list_select_related = ("sale", "payment_transaction")
    readonly_fields = tuple(field.name for field in SalePayment._meta.fields)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(PaymentReconciliation)
class PaymentReconciliationAdmin(admin.ModelAdmin):
    list_display = ("reconciled_at", "reference_snapshot", "decision", "reconciled_by")
    list_filter = ("decision", "reconciled_at")
    search_fields = ("reference_snapshot", "reason")
    readonly_fields = tuple(field.name for field in PaymentReconciliation._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("payments.view_paymentreconciliation")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CashSession)
class CashSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "cashier", "opened_at", "opening_float", "status", "expected_cash", "counted_cash", "variance")
    list_filter = ("status", "opened_at")
    readonly_fields = tuple(field.name for field in CashSession._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("payments.view_cashsession")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(CashSessionMovement)
class CashSessionMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "session", "movement_type", "amount", "actor", "reason")
    list_filter = ("movement_type", "created_at")
    readonly_fields = tuple(field.name for field in CashSessionMovement._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("payments.view_cashsessionmovement")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(RefundPayout)
class RefundPayoutAdmin(admin.ModelAdmin):
    list_display = ("issued_at", "refund", "method", "amount", "reference", "verification_status", "issued_by")
    list_filter = ("method", "issued_at")
    readonly_fields = tuple(field.name for field in RefundPayout._meta.fields) + ("verification_status",)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("payments.view_refundpayout")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(PayoutReconciliation)
class PayoutReconciliationAdmin(admin.ModelAdmin):
    list_display = ("reconciled_at", "decision", "reference_snapshot", "reconciled_by")
    list_filter = ("decision", "reconciled_at")
    readonly_fields = tuple(field.name for field in PayoutReconciliation._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return request.user.is_superuser or request.user.has_perm("payments.view_payoutreconciliation")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(MpesaStkPush)
class MpesaStkPushAdmin(admin.ModelAdmin):
    list_display = (
        "payment_reference",
        "created_at",
        "payment_amount",
        "phone_display",
        "status_badge",
        "checkout_request_id",
        "mpesa_receipt_number",
        "callback_received_at",
    )
    list_display_links = ("payment_reference",)
    list_filter = ("status", "created_at")
    date_hierarchy = "created_at"
    search_fields = (
        "phone_number",
        "checkout_request_id",
        "merchant_request_id",
        "mpesa_receipt_number",
        "payment_transaction__reference",
    )
    list_select_related = ("payment_transaction",)
    exclude = ("callback_token", "callback_payload")
    readonly_fields = tuple(
        field.name for field in MpesaStkPush._meta.fields
        if field.name not in {"callback_token", "callback_payload"}
    )
    fieldsets = (
        ("Payment", {"fields": ("payment_transaction", "phone_number", "status")}),
        ("Daraja request", {"fields": ("merchant_request_id", "checkout_request_id")}),
        ("Callback result", {"fields": ("result_code", "result_description", "mpesa_receipt_number", "callback_received_at")}),
        ("Record timestamps", {"fields": ("created_at", "updated_at")}),
    )
    actions = None

    @admin.display(description="Payment reference", ordering="payment_transaction__reference")
    def payment_reference(self, obj):
        return obj.payment_transaction.reference

    @admin.display(description="Amount (KES)", ordering="payment_transaction__amount")
    def payment_amount(self, obj):
        return f"KSh {obj.payment_transaction.amount:,.2f}"

    @admin.display(description="Phone")
    def phone_display(self, obj):
        phone = obj.phone_number or ""
        if len(phone) < 8:
            return "••••"
        return f"{phone[:5]}•••{phone[-3:]}"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return obj.get_status_display()

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("payment_transaction")

    def changelist_view(self, request, extra_context=None):
        queryset = self.get_queryset(request)
        extra_context = {
            **(extra_context or {}),
            "stk_push_summary": {
                "pending_count": queryset.filter(status=MpesaStkPush.Status.PENDING).count(),
                "unknown_count": queryset.filter(status=MpesaStkPush.Status.UNKNOWN).count(),
                "succeeded_count": queryset.filter(status=MpesaStkPush.Status.SUCCEEDED).count(),
                "failed_count": queryset.filter(status=MpesaStkPush.Status.FAILED).count(),
            },
        }
        return super().changelist_view(request, extra_context=extra_context)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm("payments.view_mpesastkpush")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MpesaC2BPayment)
class MpesaC2BPaymentAdmin(admin.ModelAdmin):
    list_display = ("received_at", "payment_transaction", "business_shortcode", "payer_first_name", "masked_msisdn", "transacted_at")
    list_filter = ("business_shortcode", "received_at")
    search_fields = ("payment_transaction__reference", "payer_first_name", "payer_last_name", "bill_ref_number")
    readonly_fields = tuple(field.name for field in MpesaC2BPayment._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm("payments.view_mpesac2bpayment")

    def has_delete_permission(self, request, obj=None):
        return False
