import base64
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from core.models import IntegrationSettings
from sales.models import Sale
from .models import MpesaStkPush, PaymentTransaction, SalePayment

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


class DarajaError(Exception):
    pass


class DarajaOutcomeUnknown(DarajaError):
    pass


def normalize_mpesa_phone(value):
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith(("07", "01")):
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits.startswith(("7", "1")):
        digits = "254" + digits
    if len(digits) != 12 or not digits.startswith(("2547", "2541")):
        raise ValidationError({"phone": "Enter a valid Kenyan Safaricom number, e.g. 0712345678."})
    return digits


def _root(config):
    return (
        "https://api.safaricom.co.ke"
        if config.get("mpesa_environment") == "production"
        else "https://sandbox.safaricom.co.ke"
    )


def _read_json_response(request, timeout=15):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(16384).decode("utf-8", errors="replace")
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        # Error bodies are not logged because gateway responses can contain
        # identifying request data. The HTTP code is sufficient for support.
        raise DarajaError(f"Daraja returned HTTP {exc.code}. Check the app credentials and environment.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DarajaOutcomeUnknown("Daraja could not be reached. The payment outcome is not yet known.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise DarajaError("Daraja returned an unreadable response.") from None


def _access_token(config):
    consumer_key = (config.get("mpesa_consumer_key") or "").strip()
    consumer_secret = (config.get("mpesa_consumer_secret") or "").strip()
    if not (consumer_key and consumer_secret):
        raise DarajaError("Enter the Daraja consumer key and consumer secret in API Integrations.")
    cache_key = "lashpro:daraja:token:" + hashlib.sha256(
        (_root(config) + ":" + consumer_key).encode("utf-8")
    ).hexdigest()
    token = cache.get(cache_key)
    if token:
        return token
    basic = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        _root(config) + "/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": "Basic " + basic, "Accept": "application/json"},
        method="GET",
    )
    try:
        status, payload = _read_json_response(request, timeout=12)
    except DarajaOutcomeUnknown:
        # OAuth happens before the STK request, so it is safe to tell the user
        # that a prompt was not submitted when the token request itself failed.
        raise DarajaError("Could not authenticate with Daraja. Check the consumer key, secret and environment.") from None
    token = payload.get("access_token")
    if status not in (200, 201) or not token:
        raise DarajaError("Daraja authentication failed. Check the consumer key, secret and environment.")
    cache.set(cache_key, token, 3500)
    return token


def _validate_amount(value):
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid KSh amount."}) from None
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValidationError({"amount": "M-Pesa STK Push requires a positive whole-KSh amount."})
    return amount


def _stk_request(config, amount, phone, callback_url):
    shortcode = (config.get("mpesa_shortcode") or "").strip()
    passkey = (config.get("mpesa_passkey") or "").strip()
    if not (shortcode and passkey):
        raise DarajaError("Enter the Daraja business short code and Lipa Na M-Pesa passkey.")
    access_token = _access_token(config)
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    ).decode("ascii")
    account_reference = (config.get("mpesa_account_reference") or "LashPro")[:12]
    description = (config.get("mpesa_transaction_description") or "POS Payment")[:13]
    transaction_type = config.get("mpesa_transaction_type") or "CustomerPayBillOnline"
    party_b = (config.get("mpesa_party_b") or shortcode).strip()
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": party_b,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": account_reference,
        "TransactionDesc": description,
    }
    request = urllib.request.Request(
        _root(config) + "/mpesa/stkpush/v1/processrequest",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _read_json_response(request, timeout=20)[1]


@transaction.atomic
def _reserve_payment(*, sale, amount, phone, callback_token, idempotency_key, actor):
    sale_id = sale.pk if isinstance(sale, Sale) else sale
    try:
        locked_sale = Sale.objects.select_for_update().get(pk=sale_id)
    except (Sale.DoesNotExist, TypeError, ValueError):
        raise ValidationError({"sale": "Sale does not exist."}) from None
    if locked_sale.status != Sale.Status.COMPLETED:
        raise ValidationError({"sale": "STK Push is available only for completed sales."})
    if not getattr(actor, "is_active", False) or not (
        actor.is_superuser or getattr(actor, "role", None) in {
            User.Role.OWNER, User.Role.MANAGER, User.Role.CASHIER
        }
    ):
        raise ValidationError({"actor": "You are not allowed to collect this payment."})

    existing = PaymentTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        allocation = SalePayment.objects.filter(payment_transaction=existing).first()
        if (
            existing.method == PaymentTransaction.Method.MPESA
            and allocation and allocation.sale_id == locked_sale.pk
            and allocation.amount == amount
        ):
            try:
                existing_push = existing.stk_push
            except MpesaStkPush.DoesNotExist:
                raise ValidationError({"idempotency_key": "This checkout key has already been used."}) from None
            if existing_push.phone_number == phone:
                return existing_push, False
        raise ValidationError({"idempotency_key": "This payment request key has already been used with different details."})
        raise ValidationError({"idempotency_key": "This payment request key has already been used."})

    if amount > locked_sale.available_to_collect:
        raise ValidationError({"amount": "STK Push amount exceeds the sale balance still available to collect."})

    placeholder = "STK-" + secrets.token_hex(10).upper()
    payment = PaymentTransaction(
        amount=amount,
        method=PaymentTransaction.Method.MPESA,
        status=PaymentTransaction.Status.UNVERIFIED,
        reference=placeholder,
        idempotency_key=idempotency_key,
        recorded_by=actor,
    )
    payment.full_clean()
    payment.save()
    SalePayment.objects.create(
        sale=locked_sale,
        payment_transaction=payment,
        amount=amount,
    )
    push = MpesaStkPush.objects.create(
        payment_transaction=payment,
        callback_token=callback_token,
        phone_number=phone,
    )
    return push, True


@transaction.atomic
def _update_push_before_callback(push_id, updates, payment_status=None):
    locked = MpesaStkPush.objects.select_for_update().select_related(
        "payment_transaction"
    ).get(pk=push_id)
    # A very fast callback can arrive before the initial HTTP response is saved.
    # Never let that response overwrite a callback-confirmed result.
    if locked.callback_received_at:
        return locked, True
    for field, value in updates.items():
        setattr(locked, field, value)
    locked.save(update_fields=tuple(updates.keys()) + ("updated_at",))
    if payment_status:
        payment = locked.payment_transaction
        payment.status = payment_status
        payment.save(update_fields=("status",))
    return locked, False


def initiate_stk_push(
    *, sale, amount, phone, callback_url, callback_token=None,
    idempotency_key=None, actor,
):
    config = IntegrationSettings.get_solo().get_config()
    required = ("mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_shortcode", "mpesa_passkey")
    if not all(config.get(key) for key in required):
        raise ValidationError({"mpesa": "Daraja is not configured. Add the consumer key, secret, short code and passkey in Admin Suite → API Integrations."})

    amount = _validate_amount(amount)
    phone = normalize_mpesa_phone(phone)
    try:
        key = uuid.UUID(str(idempotency_key)) if idempotency_key else uuid.uuid4()
    except (TypeError, ValueError, AttributeError):
        raise ValidationError({"idempotency_key": "Invalid payment request key."}) from None
    callback_token = callback_token or secrets.token_urlsafe(48)

    push, created = _reserve_payment(
        sale=sale, amount=amount, phone=phone, callback_token=callback_token,
        idempotency_key=key, actor=actor,
    )
    if not created:
        return push

    try:
        payload = _stk_request(config, amount, phone, callback_url)
    except DarajaOutcomeUnknown as exc:
        push, callback_won = _update_push_before_callback(
            push.pk,
            {
                "status": MpesaStkPush.Status.UNKNOWN,
                "result_description": str(exc)[:500],
            },
        )
        if callback_won:
            return push
        raise ValidationError({"mpesa": "The request outcome is not yet known. Do not send another prompt; wait for the callback or check the M-Pesa account."}) from None
    except DarajaError as exc:
        push, callback_won = _update_push_before_callback(
            push.pk,
            {
                "status": MpesaStkPush.Status.FAILED,
                "result_description": str(exc)[:500],
            },
            payment_status=PaymentTransaction.Status.FAILED,
        )
        if callback_won:
            return push
        raise ValidationError({"mpesa": str(exc)}) from None

    response_code = str(payload.get("ResponseCode", ""))
    if response_code != "0" or not payload.get("CheckoutRequestID"):
        push, callback_won = _update_push_before_callback(
            push.pk,
            {
                "status": MpesaStkPush.Status.FAILED,
                "result_code": response_code,
                "result_description": str(
                    payload.get("ResponseDescription")
                    or payload.get("errorMessage")
                    or "Daraja did not accept the STK request."
                )[:500],
            },
            payment_status=PaymentTransaction.Status.FAILED,
        )
        if callback_won:
            return push
        raise ValidationError({"mpesa": "Daraja rejected the STK request. Check the credentials, shortcode, passkey and transaction type."})

    push, callback_won = _update_push_before_callback(
        push.pk,
        {
            "merchant_request_id": str(payload.get("MerchantRequestID") or "")[:100],
            "checkout_request_id": str(payload.get("CheckoutRequestID") or "")[:100],
            "status": MpesaStkPush.Status.PENDING,
            "result_description": str(payload.get("CustomerMessage") or "STK prompt sent to customer.")[:500],
        },
    )
    return push


@transaction.atomic
def process_stk_callback(*, callback_token, payload):
    try:
        push = MpesaStkPush.objects.select_for_update().select_related(
            "payment_transaction"
        ).get(callback_token=callback_token)
    except MpesaStkPush.DoesNotExist:
        raise ValidationError("Unknown M-Pesa callback token.") from None

    body = (payload or {}).get("Body") if isinstance(payload, dict) else None
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    if not isinstance(callback, dict):
        raise ValidationError("Invalid M-Pesa callback format.")
    checkout_id = str(callback.get("CheckoutRequestID") or "")
    if push.checkout_request_id and checkout_id != push.checkout_request_id:
        raise ValidationError("M-Pesa callback does not match this checkout request.")
    if push.callback_received_at:
        return push

    result_code = str(callback.get("ResultCode", ""))
    result_description = str(callback.get("ResultDesc") or "")[:500]
    metadata = {}
    callback_metadata = callback.get("CallbackMetadata")
    items = callback_metadata.get("Item", []) if isinstance(callback_metadata, dict) else []
    for item in items or []:
        if isinstance(item, dict) and item.get("Name"):
            metadata[item["Name"]] = item.get("Value")
    receipt = str(metadata.get("MpesaReceiptNumber") or "").strip().upper()[:50]

    payment = push.payment_transaction
    if result_code == "0" and receipt:
        # The callback is accepted only when its transaction facts match the
        # reserved amount and the phone to which the prompt was sent.
        try:
            reported_amount = Decimal(str(metadata.get("Amount"))).quantize(CENT)
            reported_phone = normalize_mpesa_phone(metadata.get("PhoneNumber"))
        except (InvalidOperation, TypeError, ValueError, ValidationError):
            raise ValidationError("Successful M-Pesa callback is missing valid amount or phone metadata.") from None
        if reported_amount != payment.amount or reported_phone != push.phone_number:
            raise ValidationError("M-Pesa callback amount or phone does not match the STK payment request.")
        push.status = MpesaStkPush.Status.SUCCEEDED
        push.mpesa_receipt_number = receipt
        payment.status = PaymentTransaction.Status.SUCCEEDED
    else:
        push.status = MpesaStkPush.Status.FAILED
        payment.status = PaymentTransaction.Status.FAILED

    push.result_code = result_code[:20]
    push.result_description = result_description
    push.callback_payload = payload
    push.callback_received_at = timezone.now()
    push.save(update_fields=(
        "status", "mpesa_receipt_number", "result_code",
        "result_description", "callback_payload", "callback_received_at",
        "updated_at",
    ))
    payment.save(update_fields=("status",))
    return push
