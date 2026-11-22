import hashlib
import hmac
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import IntegrationSettings
from storefront.models import WhatsAppOrderInbox

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 1_048_576


def _config():
    record = IntegrationSettings.objects.filter(pk=1).first()
    if not record:
        return {}
    try:
        return record.get_config()
    except RuntimeError:
        logger.exception("WhatsApp webhook settings could not be decrypted.")
        return {}


def _valid_signature(request, app_secret):
    supplied = request.headers.get("X-Hub-Signature-256", "")
    if not supplied.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        request.body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(supplied, expected)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    """Verify Meta's callback and persist customer catalogue order messages."""
    config = _config()

    if request.method == "GET":
        verify_token = (config.get("whatsapp_webhook_verify_token") or "").strip()
        mode = request.GET.get("hub.mode", "")
        supplied = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        if (
            mode == "subscribe"
            and verify_token
            and hmac.compare_digest(supplied, verify_token)
            and challenge
        ):
            return HttpResponse(challenge, content_type="text/plain; charset=utf-8")
        return HttpResponse("Webhook verification failed.", status=403, content_type="text/plain; charset=utf-8")

    if len(request.body) > MAX_WEBHOOK_BYTES:
        return JsonResponse({"error": "Webhook payload too large."}, status=413)

    app_secret = (config.get("whatsapp_app_secret") or "").strip()
    if not app_secret or not _valid_signature(request, app_secret):
        return JsonResponse({"error": "Invalid webhook signature."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    expected_waba_id = str(config.get("whatsapp_business_account_id") or "").strip()
    for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
        entry_waba_id = str(entry.get("id") or "").strip()
        if expected_waba_id and entry_waba_id and entry_waba_id != expected_waba_id:
            logger.warning("Ignored WhatsApp webhook event for an unconfigured business account.")
            continue
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            contacts = value.get("contacts") or []
            names_by_phone = {
                str(contact.get("wa_id") or "").strip(): str(
                    (contact.get("profile") or {}).get("name") or ""
                ).strip()
                for contact in contacts
                if isinstance(contact, dict)
            }
            for message in value.get("messages") or []:
                if not isinstance(message, dict) or message.get("type") != "order":
                    continue
                message_id = str(message.get("id") or "").strip()
                sender_phone = str(message.get("from") or "").strip()
                order_payload = message.get("order")
                if not message_id or not sender_phone or not isinstance(order_payload, dict):
                    logger.warning("Ignored malformed WhatsApp catalogue order webhook.")
                    continue
                catalog_id = str(order_payload.get("catalog_id") or "").strip()
                WhatsAppOrderInbox.objects.get_or_create(
                    message_id=message_id,
                    defaults={
                        "sender_phone": sender_phone,
                        "customer_name": names_by_phone.get(sender_phone, "")[:100],
                        "catalog_id": catalog_id,
                        "order_payload": order_payload,
                    },
                )

    return JsonResponse({"received": True}, status=200)
