import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from core.models import IntegrationSettings

logger = logging.getLogger(__name__)

EVENT_COPY = {
    "REQUESTED": {
        "subject": "We received your LashPro appointment request",
        "heading": "Appointment request received",
        "body": "Your appointment request has been received. The studio will contact you after it has reviewed the schedule.",
    },
    "CONFIRMED": {
        "subject": "Your LashPro appointment is confirmed",
        "heading": "Appointment confirmed",
        "body": "Your appointment is confirmed. We look forward to seeing you.",
    },
    "CANCELLED": {
        "subject": "Your LashPro appointment has been cancelled",
        "heading": "Appointment cancelled",
        "body": "Your appointment has been cancelled. Contact the studio if you need assistance.",
    },
}


def _phone_e164(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits.startswith(("7", "1")):
        digits = "254" + digits
    elif digits.startswith("254") and len(digits) == 12:
        pass
    else:
        return ""
    return "+" + digits


def _appointment_message(appointment, event):
    copy = EVENT_COPY[event]
    starts = appointment.starts_at.strftime("%a %d %b %Y, %I:%M %p")
    staff = appointment.staff.get_full_name().strip() or appointment.staff.username
    return (
        f"{copy['heading']}, {appointment.customer_name}. "
        f"{appointment.service_name_snapshot} with {staff} on {starts}. "
        f"Reference: {appointment.reference}. {copy['body']}"
    )


def _post_form(url, data, headers, timeout=12):
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(8192).decode("utf-8", errors="replace")


def _post_json(url, payload, headers, timeout=12):
    encoded = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(8192).decode("utf-8", errors="replace")


def _send_email(config, appointment, event, body):
    recipient = (appointment.customer_email or "").strip()
    if not recipient:
        return
    from_email = config.get("email_from_email") or settings.DEFAULT_FROM_EMAIL
    if config.get("email_host"):
        connection = EmailBackend(
            host=config.get("email_host"),
            port=int(config.get("email_port") or 587),
            username=config.get("email_username") or None,
            password=config.get("email_password") or None,
            use_tls=bool(config.get("email_use_tls")),
            timeout=10,
        )
        EmailMessage(
            EVENT_COPY[event]["subject"], body, from_email, [recipient],
            connection=connection,
        ).send(fail_silently=False)
    else:
        EmailMessage(
            EVENT_COPY[event]["subject"], body, from_email, [recipient],
        ).send(fail_silently=False)


def _send_sms(config, appointment, body):
    if config.get("sms_provider") != "africastalking":
        return
    phone = _phone_e164(appointment.customer_phone)
    if not phone or not config.get("sms_api_key") or not config.get("sms_username"):
        return
    sandbox = bool(config.get("sms_sandbox"))
    endpoint = (
        "https://api.sandbox.africastalking.com/version1/messaging"
        if sandbox else "https://api.africastalking.com/version1/messaging"
    )
    data = {"username": config["sms_username"], "to": phone, "message": body}
    if config.get("sms_sender_id") and not sandbox:
        data["from"] = config["sms_sender_id"]
    _post_form(endpoint, data, {
        "apiKey": config["sms_api_key"],
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    })


def _send_whatsapp(config, appointment, event):
    token = config.get("whatsapp_access_token")
    phone_number_id = config.get("whatsapp_phone_number_id")
    template_name = config.get(f"whatsapp_template_{event.lower()}")
    phone = _phone_e164(appointment.customer_phone)
    if not (token and phone_number_id and template_name and phone):
        return
    version = (config.get("whatsapp_api_version") or "v27.0").strip()
    language = config.get("whatsapp_language") or "en"
    staff = appointment.staff.get_full_name().strip() or appointment.staff.username
    params = [
        appointment.customer_name,
        appointment.service_name_snapshot,
        appointment.starts_at.strftime("%d %b %Y"),
        appointment.starts_at.strftime("%I:%M %p") + " · " + staff,
    ]
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": value} for value in params],
            }],
        },
    }
    _post_json(
        f"https://graph.facebook.com/{version}/{phone_number_id}/messages",
        payload,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def send_booking_notification(appointment, event):
    """Send best-effort customer updates; provider outages never undo a booking."""
    if event not in EVENT_COPY:
        return
    try:
        config = IntegrationSettings.get_solo().get_config()
    except Exception:
        logger.exception("Could not load encrypted integration settings.")
        return

    body = _appointment_message(appointment, event)
    senders = (
        ("email", lambda: _send_email(config, appointment, event, body)),
        ("sms", lambda: _send_sms(config, appointment, body)),
        ("whatsapp", lambda: _send_whatsapp(config, appointment, event)),
    )
    for channel, sender in senders:
        try:
            sender()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
            logger.warning(
                "Appointment %s notification failed on %s.",
                appointment.reference, channel, exc_info=True,
            )
        except Exception:
            logger.exception(
                "Appointment %s notification failed on %s.",
                appointment.reference, channel,
            )
