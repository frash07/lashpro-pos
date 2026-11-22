import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from catalog.models import Product

from .models import StorefrontStockReservation

logger = logging.getLogger(__name__)


def _publish_product(product_id):
    from .whatsapp import enqueue_product_catalog_sync

    try:
        enqueue_product_catalog_sync(product_id)
    except Exception:
        # A Meta outage must never undo a POS sale, stock movement, or order.
        logger.exception("Could not enqueue WhatsApp catalogue sync for product %s.", product_id)


@receiver(post_save, sender=Product)
def sync_product_after_catalog_or_stock_change(sender, instance, **kwargs):
    product_id = instance.pk
    transaction.on_commit(lambda: _publish_product(product_id))


@receiver(post_save, sender=StorefrontStockReservation)
def sync_product_after_online_reservation_change(sender, instance, **kwargs):
    product_id = instance.product_id
    transaction.on_commit(lambda: _publish_product(product_id))
