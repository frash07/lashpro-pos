import json
import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from core.models import IntegrationSettings
from commissions.models import CommissionPayoutRecord
from .forms import CashSessionApprovalForm, CashSessionMovementForm, CloseCashSessionForm, OpenCashSessionForm
from sales.models import Sale
from .models import CashSession, CashSessionMovement, MpesaC2BPayment, MpesaStkPush, PaymentTransaction, RefundPayout
from .mpesa import (
    DarajaError, configured_c2b_shortcodes, initiate_stk_push,
    process_c2b_callback, process_stk_callback, register_c2b_urls,
)
from .stk_reconciliation import query_sandbox_stk
from .services import (
    add_cash_session_movement, allocate_c2b_mpesa_payment, approve_cash_session_close, calculate_expected_cash,
    close_cash_session, open_cash_session, reconcile_manual_mpesa,
)


logger = logging.getLogger(__name__)


def _manager(user):
    return user.is_superuser or getattr(user, "role", None) in {User.Role.OWNER, User.Role.MANAGER}


def _can_use_cash_tools(user):
    return _manager(user) or getattr(user, "role", None) == User.Role.CASHIER


@login_required(login_url="login")
def reconciliation_queue(request):
    if not _manager(request.user):
        raise PermissionDenied
    if request.method == "POST":
        reason = request.POST.get("reason", "")
        try:
            if request.POST.get("stk_id"):
                outcome = query_sandbox_stk(
                    push_id=request.POST["stk_id"], actor=request.user,
                    legacy_confirmed=request.POST.get("legacy_confirmed") == "yes",
                    close_cancelled=request.POST.get("stk_action") == "close_cancelled",
                )
                messages.info(request, outcome)
                return redirect("payments:reconciliation")
            if request.POST.get("payout_id"):
                from .services import reconcile_mpesa_payout
                reconcile_mpesa_payout(payout_type=request.POST.get("payout_type", ""), payout=request.POST.get("payout_id"), actor=request.user, decision=request.POST.get("decision", ""), reason=reason)
                label = "M-Pesa payout"
            else:
                payment = get_object_or_404(PaymentTransaction, pk=request.POST.get("payment_id"))
                reconcile_manual_mpesa(payment=payment, actor=request.user, decision=request.POST.get("decision", ""), reason=reason)
                label = f"Payment {payment.reference}"
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"{label} reconciled.")
        return redirect("payments:reconciliation")
    pending = PaymentTransaction.objects.filter(
        method=PaymentTransaction.Method.MPESA,
        status=PaymentTransaction.Status.UNVERIFIED,
        stk_push__isnull=True,
    ).select_related(
        "sale_allocation__sale__customer",
        "sale_allocation__sale__training_enrollment__cohort__course",
    ).order_by("created_at")
    pending_stk = list(MpesaStkPush.objects.filter(
        status__in=(MpesaStkPush.Status.PENDING, MpesaStkPush.Status.UNKNOWN),
        payment_transaction__status=PaymentTransaction.Status.UNVERIFIED,
    ).select_related("payment_transaction__sale_allocation__sale").order_by("created_at"))
    push_ids = [str(push.pk) for push in pending_stk]
    origins = set(AuditEvent.objects.filter(
        object_type="mpesa_stk_origin", object_id__in=push_ids,
    ).values_list("object_id", flat=True))
    latest_queries = {}
    for event in AuditEvent.objects.filter(
        object_type="mpesa_stk_query", object_id__in=push_ids,
    ).order_by("-created_at", "-pk"):
        latest_queries.setdefault(event.object_id, event)
    for push in pending_stk:
        push.legacy_origin = str(push.pk) not in origins
        push.latest_query = latest_queries.get(str(push.pk))
    stk_conflicts = AuditEvent.objects.filter(
        object_type="mpesa_stk_conflict",
    ).order_by("-created_at", "-pk")[:50]
    sandbox_query_enabled = IntegrationSettings.get_solo().get_config().get("mpesa_environment") == "sandbox"
    pending_refunds = RefundPayout.objects.filter(method="MPESA", payout_reconciliation__isnull=True).select_related("refund__sale")
    pending_commissions = CommissionPayoutRecord.objects.filter(method="MPESA", payout_reconciliation__isnull=True).select_related("technician")
    from core.admin_workspace import operational_workspace
    return render(request, "payments/reconciliation.html", {
        **operational_workspace(request, "M-Pesa reconciliation", "reconciliation"),
        "pending_payments": pending,
        "pending_stk": pending_stk,
        "stk_conflicts": stk_conflicts,
        "sandbox_query_enabled": sandbox_query_enabled,
        "pending_refund_payouts": pending_refunds,
        "pending_commission_payouts": pending_commissions,
    })


@login_required(login_url="login")
def cash_session_dashboard(request):
    if not _can_use_cash_tools(request.user):
        raise PermissionDenied
    own_session = CashSession.objects.filter(cashier=request.user, status__in=(CashSession.Status.OPEN, CashSession.Status.PENDING_APPROVAL)).first()
    action = request.POST.get("action", "") if request.method == "POST" else ""
    try:
        if request.method == "POST" and action == "open":
            open_cash_session(cashier=request.user, opening_float=request.POST.get("opening_float"), actor=request.user)
            messages.success(request, "Cash session opened.")
        elif request.method == "POST" and action == "close" and own_session:
            close_cash_session(session=own_session, counted_cash=request.POST.get("counted_cash"), actor=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, "Cash session close recorded.")
        elif request.method == "POST" and action == "approve" and _manager(request.user):
            pending = get_object_or_404(CashSession, pk=request.POST.get("session_id"), status=CashSession.Status.PENDING_APPROVAL)
            approve_cash_session_close(session=pending, approver=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, "Cash variance approved.")
        elif request.method == "POST" and action == "movement" and own_session:
            form = CashSessionMovementForm(request.POST)
            if not form.is_valid():
                raise ValidationError(form.errors.as_text())
            data = form.cleaned_data
            if data["movement_type"] == CashSessionMovement.Type.EXPENSE:
                from expenses.models import Expense
                from expenses.services import record_expense
                record_expense(
                    actor=request.user,
                    category=Expense.Category.OTHER,
                    description=data["reason"],
                    amount=data["amount"],
                    expense_date=timezone.localdate(),
                    payment_status=Expense.PaymentStatus.PAID,
                    payment_method=Expense.PaymentMethod.CASH,
                    cash_session=own_session,
                )
                messages.success(request, "Cash expense recorded in the expense register and drawer ledger.")
            else:
                amount = data["amount"] if data["movement_type"] == "CASH_IN" else -data["amount"]
                add_cash_session_movement(session=own_session, movement_type=data["movement_type"], amount=amount, reason=data["reason"], actor=request.user)
                messages.success(request, "Cash movement recorded.")
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    return redirect("payments:cash-session") if request.method == "POST" else _render_cash_session(request, own_session)


def _render_cash_session(request, own_session):
    if own_session and own_session.status == CashSession.Status.OPEN:
        own_session.expected_now = calculate_expected_cash(own_session)
    pending_sessions = CashSession.objects.filter(status=CashSession.Status.PENDING_APPROVAL).select_related("cashier", "closed_by") if _manager(request.user) else CashSession.objects.none()
    return render(request, "payments/cash_session.html", {
        "session": own_session, "open_form": OpenCashSessionForm(),
        "close_form": CloseCashSessionForm(), "movement_form": CashSessionMovementForm(),
        "pending_sessions": pending_sessions, "approval_form": CashSessionApprovalForm(),
        "is_manager": _manager(request.user),
    })



@login_required(login_url="login")
@require_POST
def mpesa_stk_initiate(request):
    if not _can_use_cash_tools(request.user):
        raise PermissionDenied
    sale = get_object_or_404(Sale, pk=request.POST.get("sale_id"), status=Sale.Status.COMPLETED)
    if not _manager(request.user) and sale.cashier_id != request.user.pk:
        raise PermissionDenied

    callback_token = secrets.token_urlsafe(48)
    callback_url = (
        settings.POS_BASE_URL.rstrip("/")
        + reverse("payments:mpesa-stk-callback", kwargs={"token": callback_token})
    )
    try:
        push = initiate_stk_push(
            sale=sale,
            amount=request.POST.get("amount"),
            phone=request.POST.get("phone"),
            callback_url=callback_url,
            callback_token=callback_token,
            idempotency_key=request.POST.get("idempotency_key"),
            actor=request.user,
        )
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
    else:
        if push.status == MpesaStkPush.Status.PENDING:
            messages.success(request, f"M-Pesa prompt sent to {push.phone_number}. The sale is paid only after Daraja confirms the callback.")
        elif push.status == MpesaStkPush.Status.SUCCEEDED:
            messages.success(request, f"M-Pesa payment for {sale.receipt_number} is confirmed.")
        elif push.status == MpesaStkPush.Status.UNKNOWN:
            messages.warning(request, "Daraja did not return a definite response. Do not send another STK prompt until the payment outcome is checked.")
        else:
            messages.error(request, "The STK request was not accepted. Check the Daraja settings and try again.")
    return redirect("sales:payments")


@csrf_exempt
@require_POST
def mpesa_stk_callback(request, token):
    try:
        if len(request.body) > 65536:
            return JsonResponse({"ResultCode": 1, "ResultDesc": "Payload too large"}, status=413)
        payload = json.loads(request.body.decode("utf-8"))
        push = process_stk_callback(callback_token=token, payload=payload)
    except (ValueError, UnicodeDecodeError, ValidationError):
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid callback"}, status=400)
    return JsonResponse({
        "ResultCode": 0,
        "ResultDesc": "Accepted",
        "payment_status": push.status,
    })



@login_required(login_url="login")
@require_POST
def register_c2b_callbacks(request):
    """Register Daraja C2B v2 confirmation and validation URLs for configured codes."""
    if not _manager(request.user):
        raise PermissionDenied
    from core.models import IntegrationSettings

    record = IntegrationSettings.get_solo()
    try:
        config = record.get_config()
        shortcodes = configured_c2b_shortcodes(config)
        if not shortcodes:
            raise ValidationError({"mpesa_c2b_shortcodes": "Save at least one Paybill or Till callback shortcode in API Integrations first."})
        base_url = str(settings.POS_BASE_URL or "").rstrip("/")
        if not base_url.startswith("https://"):
            raise ValidationError({"POS_BASE_URL": "Set POS_BASE_URL to the public HTTPS address of this POS before registering C2B callbacks."})
        token = str(config.get("mpesa_c2b_callback_token") or "")
        if not token:
            token = secrets.token_urlsafe(48)
            config["mpesa_c2b_callback_token"] = token
            record.set_config(config)
            record.updated_by = request.user
            record.save(update_fields=("encrypted_config", "updated_by", "updated_at"))
        confirmation_url = base_url + reverse("payments:c2b-confirmation", kwargs={"token": token})
        validation_url = base_url + reverse("payments:c2b-validation", kwargs={"token": token})
        registered = register_c2b_urls(
            config=config,
            shortcodes=shortcodes,
            confirmation_url=confirmation_url,
            validation_url=validation_url,
        )
    except (ValidationError, DarajaError, RuntimeError) as exc:
        errors = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        for error in errors:
            messages.error(request, error)
    else:
        messages.success(request, "C2B callback URLs registered for shortcodes: " + ", ".join(registered) + ".")
    return redirect("integrations-settings")


@csrf_exempt
@require_POST
def c2b_validation(request, token):
    """C2B is registered with ResponseType=Completed, so accept validation if called."""
    from core.models import IntegrationSettings

    try:
        config = IntegrationSettings.get_solo().get_config()
        expected = str(config.get("mpesa_c2b_callback_token") or "")
        if not expected or not secrets.compare_digest(str(token or ""), expected):
            return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid callback"}, status=403)
    except RuntimeError:
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Callback configuration unavailable"}, status=503)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


@csrf_exempt
@require_POST
def c2b_confirmation(request, token):
    try:
        if len(request.body) > 65536:
            return JsonResponse({"ResultCode": 1, "ResultDesc": "Payload too large"}, status=413)
        payload = json.loads(request.body.decode("utf-8"))
        record = process_c2b_callback(callback_token=token, payload=payload)
    except (ValueError, UnicodeDecodeError, ValidationError) as exc:
        reason = exc.messages[0] if isinstance(exc, ValidationError) and exc.messages else "invalid payload"
        logger.warning("Rejected C2B confirmation callback: %s", reason[:160])
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid callback"}, status=400)
    return JsonResponse({
        "ResultCode": 0,
        "ResultDesc": "Accepted",
        "payment_status": record.payment_transaction.status,
    })


@login_required(login_url="login")
def c2b_inbox(request):
    if not _can_use_cash_tools(request.user):
        raise PermissionDenied
    is_manager = _manager(request.user)
    if request.method == "POST":
        sale_queryset = Sale.objects.filter(status=Sale.Status.COMPLETED)
        if not is_manager:
            sale_queryset = sale_queryset.filter(cashier=request.user)
        sale = get_object_or_404(sale_queryset, pk=request.POST.get("sale_id"))
        try:
            allocate_c2b_mpesa_payment(
                c2b_payment=request.POST.get("payment_id"),
                sale=sale,
                actor=request.user,
                customer_confirmed=request.POST.get("customer_confirmed") == "on",
            )
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            messages.success(request, f"M-Pesa payment allocated to {sale.receipt_number}.")
        return redirect("payments:c2b-inbox")

    incoming = MpesaC2BPayment.objects.filter(
        payment_transaction__sale_allocation__isnull=True,
        payment_transaction__status=PaymentTransaction.Status.SUCCEEDED,
    ).select_related("payment_transaction").order_by("-transacted_at")[:100]
    sale_queryset = Sale.objects.filter(status=Sale.Status.COMPLETED)
    if not is_manager:
        sale_queryset = sale_queryset.filter(cashier=request.user)
    sale_candidates = list(
        sale_queryset.select_related("customer", "cashier")
        .prefetch_related("payment_allocations__payment_transaction")
        .order_by("-created_at")[:300]
    )
    sale_candidates = [sale for sale in sale_candidates if sale.available_to_collect > 0]
    return render(request, "payments/c2b_inbox.html", {
        "incoming_payments": incoming,
        "sale_candidates": sale_candidates,
        "is_manager": is_manager,
    })
