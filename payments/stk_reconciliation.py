"""Manager-only sandbox STK status lookup. A query never sends another prompt."""
import base64
import json
import urllib.request
from datetime import timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event
from core.models import IntegrationSettings
from .models import MpesaStkPush, PaymentTransaction
from .mpesa import DarajaError, _access_token, _read_json_response, _root


def _query_request(config, checkout_id):
    shortcode = str(config.get("mpesa_shortcode") or "").strip()
    passkey = str(config.get("mpesa_passkey") or "").strip()
    if not shortcode.isdigit() or not passkey:
        raise ValidationError("Save a valid sandbox shortcode and passkey first.")
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode("ascii")
    token = _access_token(config)
    request = urllib.request.Request(
        _root(config) + "/mpesa/stkpushquery/v1/query",
        data=json.dumps({
            "BusinessShortCode": shortcode, "Password": password,
            "Timestamp": timestamp, "CheckoutRequestID": checkout_id,
        }).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    _, response = _read_json_response(request, timeout=15)
    return response


def _code(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    value = str(value)
    return value if value.isascii() and value.isdigit() and len(value) <= 20 else ""


def query_sandbox_stk(*, push_id, actor, legacy_confirmed=False, close_cancelled=False):
    if not actor.is_active or not (actor.is_superuser or actor.role in (User.Role.OWNER, User.Role.MANAGER)):
        raise ValidationError("Only an owner or manager may query STK payments.")
    config = IntegrationSettings.get_solo().get_config()
    if config.get("mpesa_environment") != "sandbox":
        raise ValidationError("This reconciliation pilot is restricted to sandbox mode.")
    try:
        push = MpesaStkPush.objects.select_related("payment_transaction").get(pk=push_id)
    except (MpesaStkPush.DoesNotExist, ValueError, TypeError):
        raise ValidationError("STK request not found.") from None
    if push.status not in (MpesaStkPush.Status.PENDING, MpesaStkPush.Status.UNKNOWN) or push.payment_transaction.status != PaymentTransaction.Status.UNVERIFIED:
        raise ValidationError("Only unresolved STK payments may be queried.")
    if not push.checkout_request_id:
        raise ValidationError("No checkout request ID. Investigate provider records; do not resend the prompt.")
    if push.created_at > timezone.now() - timedelta(minutes=2):
        raise ValidationError("Allow at least two minutes for the original callback.")
    origin = AuditEvent.objects.filter(object_type="mpesa_stk_origin", object_id=str(push.pk)).first()
    shortcode = str(config.get("mpesa_shortcode") or "").strip()
    if origin:
        if origin.metadata.get("environment") != "sandbox" or origin.metadata.get("shortcode") != shortcode:
            raise ValidationError("Current sandbox shortcode does not match the original payment.")
    elif not legacy_confirmed:
        raise ValidationError("Confirm that this older request used the current sandbox account before querying.")
    if not cache.add(f"lashpro:stk-query:{push.pk}", True, timeout=30):
        raise ValidationError("A recent status query is in progress or cooling down.")
    checkout_id, merchant_id = push.checkout_request_id, push.merchant_request_id
    response_code = result_code = ""
    correlated = False
    try:
        response = _query_request(config, checkout_id)
    except DarajaError:
        outcome = "Provider query unavailable. No payment status changed."
    else:
        response = response if isinstance(response, dict) else {}
        response_code = _code(response.get("ResponseCode"))
        result_code = _code(response.get("ResultCode"))
        correlated = (
            response_code == "0" and bool(result_code)
            and response.get("CheckoutRequestID") == checkout_id
            and (not merchant_id or response.get("MerchantRequestID") == merchant_id)
        )
        if not correlated:
            outcome = "Query response incomplete or not correlated. Keep the payment reserved."
        elif result_code == "0":
            outcome = "Daraja reports success. Await verified receipt and callback; do not resend."
        elif result_code == "1032":
            outcome = "Daraja reports cancellation. Review before releasing the reservation."
        else:
            outcome = f"Daraja result {result_code}. Keep the payment reserved pending review."
    with transaction.atomic():
        locked = MpesaStkPush.objects.select_for_update().select_related("payment_transaction").get(pk=push.pk)
        before = locked.status
        if (
            close_cancelled and correlated and result_code == "1032"
            and locked.status in (MpesaStkPush.Status.PENDING, MpesaStkPush.Status.UNKNOWN)
            and locked.payment_transaction.status == PaymentTransaction.Status.UNVERIFIED
            and locked.checkout_request_id == checkout_id
            and locked.merchant_request_id == merchant_id
            and not locked.callback_received_at and not locked.mpesa_receipt_number
        ):
            locked.status = MpesaStkPush.Status.FAILED
            locked.result_code = "1032"
            locked.result_description = "Cancellation verified by sandbox STK query."
            locked.save(update_fields=("status", "result_code", "result_description", "updated_at"))
            payment = locked.payment_transaction
            payment.status = PaymentTransaction.Status.FAILED
            payment.save(update_fields=("status",))
            outcome = "Verified sandbox cancellation closed. Reservation released; no new prompt was sent."
        elif locked.status != before or locked.status in (MpesaStkPush.Status.SUCCEEDED, MpesaStkPush.Status.FAILED):
            outcome = "The original payment is already finalized. Query did not change it."
        record_audit_event(
            event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION,
            object_type="mpesa_stk_query", object_id=locked.pk, actor=actor,
            reason=outcome,
            before_state={"status": before}, after_state={"status": locked.status},
            metadata={
                "environment": "sandbox", "shortcode": shortcode,
                "legacy_confirmed": bool(legacy_confirmed),
                "response_code": response_code, "result_code": result_code,
                "correlated": correlated, "close_requested": bool(close_cancelled),
            },
        )
    return outcome
