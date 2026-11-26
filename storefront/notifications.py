import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from core.models import IntegrationSettings
from .models import StorefrontOrder

logger = logging.getLogger(__name__)


def send_storefront_order_notification(order_id):
    """Send order acknowledgement and staff alert without exposing recipients to each other."""
    try:
        order = StorefrontOrder.objects.prefetch_related("lines").get(pk=order_id)
        config = IntegrationSettings.get_solo().get_config()
    except Exception:
        logger.exception("Could not load storefront order notification data.")
        return

    smtp_host = (config.get("email_host") or "").strip()
    staff_email = (config.get("operations_notification_email") or "").strip()
    customer_email = (order.customer_email or "").strip()
    if not smtp_host:
        logger.warning("Storefront order email provider is not configured; order %s notification not sent.", order.reference)
        return

    connection = EmailBackend(
        host=smtp_host,
        port=int(config.get("email_port") or 587),
        username=config.get("email_username") or None,
        password=config.get("email_password") or None,
        use_tls=bool(config.get("email_use_tls")),
        timeout=10,
    )
    from_email = config.get("email_from_email") or settings.DEFAULT_FROM_EMAIL
    lines = "\n".join(
        f"{line.quantity} × {line.name_snapshot} — KSh {line.line_total:.2f}"
        for line in order.lines.all()
    )
    customer_body = (
        f"Hello {order.customer_name},\n\n"
        f"Lashpro KE received your order request {order.reference}. The studio will confirm availability and the final amount.\n\n"
        f"{lines}\n\nEstimated total: KSh {order.total_amount:.2f}\n\n"
        "Please wait for studio confirmation before paying. Manual M-Pesa Paybill: 542542; account: 183288. "
        "Your payment is recorded only after staff verify the transaction.\n\nGirls Love Lashe — Lashpro KE"
    )
    staff_body = (
        f"New storefront order request {order.reference}\n"
        f"Customer: {order.customer_name}\nEmail: {order.customer_email}\nPhone: {order.customer_phone}\n"
        f"Estimated total: KSh {order.total_amount:.2f}\n\n{lines}\n\n"
        f"Review and confirm this order in the POS before requesting payment."
    )
    messages = []
    if customer_email:
        messages.append((customer_email, f"Order request {order.reference} received · Lashpro KE", customer_body))
    if staff_email:
        messages.append((staff_email, f"New storefront order {order.reference} · Lashpro KE", staff_body))

    for recipient, subject, body in messages:
        try:
            EmailMessage(subject, body, from_email, [recipient], connection=connection).send(fail_silently=False)
        except Exception:
            logger.exception("Storefront order %s notification failed.", order.reference)
