import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from core.models import IntegrationSettings
from .models import Product, WhatsAppCatalogSync

logger = logging.getLogger(__name__)


def _catalog_sync_is_enabled():
    record = IntegrationSettings.objects.filter(pk=1).first()
    if not record:
        return False
    try:
        config = record.get_config()
    except RuntimeError:
        logger.exception("WhatsApp catalogue settings could not be decrypted.")
        return False
    return bool(
        config.get("whatsapp_catalog_sync_enabled")
        and config.get("whatsapp_access_token")
        and config.get("whatsapp_catalog_id")
    )


def _queue_linked_product(product_id):
    if not _catalog_sync_is_enabled():
        return
    link = WhatsAppCatalogSync.objects.filter(
        product_id=product_id,
        catalog_linked=True,
    ).first()
    if not link:
        return
    link.status = WhatsAppCatalogSync.Status.PENDING
    link.attempt_count = 0
    link.next_attempt_at = timezone.now()
    link.last_error = ""
    link.save(update_fields=(
        "status", "attempt_count", "next_attempt_at", "last_error", "updated_at",
    ))


@receiver(post_save, sender=Product)
def queue_new_or_changed_product(sender, instance, created, **kwargs):
    if not _catalog_sync_is_enabled():
        return
    if created:
        # Products created after the catalogue integration is enabled use the
        # immutable LashPro SKU as their initial Meta retailer_id.
        WhatsAppCatalogSync.objects.get_or_create(
            product=instance,
            defaults={
                "retailer_id": instance.sku,
                "catalog_linked": True,
                "status": WhatsAppCatalogSync.Status.PENDING,
                "next_attempt_at": timezone.now(),
            },
        )
        return
    _queue_linked_product(instance.pk)


@receiver(post_save, sender="storefront.StorefrontStockReservation")
def queue_reserved_stock_change(sender, instance, **kwargs):
    # A storefront/WhatsApp order changes sellable stock before physical
    # on-hand stock changes. Keep Meta's displayed inventory aligned with
    # the available-to-sell quantity, not just the physical count.
    _queue_linked_product(instance.product_id)
