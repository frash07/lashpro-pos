import json
import logging
import secrets

from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import IntegrationSettings

from .whatsapp import process_whatsapp_webhook, verify_webhook_signature

logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 2 * 1024 * 1024


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    """Meta webhook verification and signed inbound WhatsApp catalogue-order receiver."""
    try:
        config = IntegrationSettings.get_solo().get_config()
    except Exception:
        logger.exception("Could not load WhatsApp webhook settings.")
        return JsonResponse({"error": "Webhook configuration unavailable."}, status=503)

    if request.method == "GET":
        mode = request.GET.get("hub.mode", "")
        supplied_token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        expected_token = config.get("whatsapp_webhook_verify_token") or ""
        if (
            mode == "subscribe"
            and expected_token
            and challenge
            and secrets.compare_digest(supplied_token, expected_token)
        ):
            return HttpResponse(challenge, content_type="text/plain; charset=utf-8")
        return HttpResponseForbidden("Webhook verification failed.")

    if len(request.body) > MAX_WEBHOOK_BYTES:
        return JsonResponse({"error": "Webhook payload is too large."}, status=413)

    app_secret = config.get("whatsapp_app_secret") or ""
    if not verify_webhook_signature(
        body=request.body,
        signature=request.headers.get("X-Hub-Signature-256", ""),
        app_secret=app_secret,
    ):
        return HttpResponseForbidden("Invalid webhook signature.")

    expected_phone_id = str(config.get("whatsapp_phone_number_id") or "")
    expected_waba_id = str(config.get("whatsapp_business_account_id") or "")
    catalog_id = str(config.get("whatsapp_catalog_id") or "")
    if not catalog_id:
        return JsonResponse({"error": "WhatsApp catalogue is not configured."}, status=503)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Invalid webhook payload."}, status=400)

    # Reject events delivered for a different phone number or WhatsApp business account.
    for entry in payload.get("entry", []) or []:
        if expected_waba_id and str(entry.get("id") or "") != expected_waba_id:
            return HttpResponseForbidden("Unexpected WhatsApp Business Account.")
        for change in entry.get("changes", []) or []:
            metadata = (change.get("value") or {}).get("metadata") or {}
            received_phone_id = str(metadata.get("phone_number_id") or "")
            if expected_phone_id and received_phone_id and received_phone_id != expected_phone_id:
                return HttpResponseForbidden("Unexpected WhatsApp phone number.")

    try:
        process_whatsapp_webhook(payload, configured_catalog_id=catalog_id)
    except Exception:
        # Return a retryable server error if Neon or order creation is temporarily unavailable.
        logger.exception("WhatsApp webhook processing failed.")
        return JsonResponse({"error": "Webhook processing failed; Meta may retry."}, status=500)

    return HttpResponse("EVENT_RECEIVED", content_type="text/plain; charset=utf-8")
