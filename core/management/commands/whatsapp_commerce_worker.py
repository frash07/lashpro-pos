import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from catalog.models import WhatsAppCatalogSync
from core.whatsapp_commerce import (
    WhatsAppCommerceError,
    _integration_config,
    import_whatsapp_order,
    sync_whatsapp_catalog_item,
)
from storefront.models import WhatsAppOrderInbox

logger = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=10)
MAX_SYNC_ATTEMPTS = 8


@transaction.atomic
def _claim_catalog_item():
    now = timezone.now()
    link = (
        WhatsAppCatalogSync.objects.select_for_update(skip_locked=True)
        .filter(
            Q(status=WhatsAppCatalogSync.Status.PENDING, next_attempt_at__lte=now)
            | Q(status=WhatsAppCatalogSync.Status.SYNCING, updated_at__lt=now - STALE_AFTER)
        )
        .order_by("next_attempt_at", "pk")
        .first()
    )
    if not link:
        return None
    link.status = WhatsAppCatalogSync.Status.SYNCING
    link.save(update_fields=("status", "updated_at"))
    return link.pk


@transaction.atomic
def _claim_inbox_order():
    now = timezone.now()
    inbox = (
        WhatsAppOrderInbox.objects.select_for_update(skip_locked=True)
        .filter(
            Q(status=WhatsAppOrderInbox.Status.PENDING, next_attempt_at__lte=now)
            | Q(status=WhatsAppOrderInbox.Status.PROCESSING, updated_at__lt=now - STALE_AFTER)
        )
        .order_by("received_at", "pk")
        .first()
    )
    if not inbox:
        return None
    inbox.status = WhatsAppOrderInbox.Status.PROCESSING
    inbox.save(update_fields=("status", "updated_at"))
    return inbox.pk


def _process_catalog_item(link_id):
    try:
        sync_whatsapp_catalog_item(link_id)
    except Exception as exc:
        link = WhatsAppCatalogSync.objects.filter(pk=link_id).first()
        if not link:
            return
        attempts = link.attempt_count + 1
        link.attempt_count = attempts
        link.last_error = str(exc)[:1000]
        if attempts >= MAX_SYNC_ATTEMPTS:
            link.status = WhatsAppCatalogSync.Status.FAILED
        else:
            link.status = WhatsAppCatalogSync.Status.PENDING
            link.next_attempt_at = timezone.now() + timedelta(seconds=min(30 * (2 ** (attempts - 1)), 3600))
        link.save(update_fields=(
            "status", "attempt_count", "last_error", "next_attempt_at", "updated_at",
        ))
        logger.warning("WhatsApp catalogue sync failed for mapping %s: %s", link_id, link.last_error)


def _process_inbox_order(inbox_id):
    try:
        order = import_whatsapp_order(inbox_id)
        logger.info("Imported WhatsApp order %s as LashPro order %s", inbox_id, order.reference)
    except Exception as exc:
        inbox = WhatsAppOrderInbox.objects.filter(pk=inbox_id).first()
        if not inbox:
            return
        inbox.status = WhatsAppOrderInbox.Status.FAILED
        inbox.attempt_count = inbox.attempt_count + 1
        inbox.last_error = str(exc)[:1000]
        inbox.processed_at = timezone.now()
        inbox.save(update_fields=("status", "attempt_count", "last_error", "processed_at"))
        logger.warning("WhatsApp order import %s requires review: %s", inbox_id, inbox.last_error)


def _work_once():
    inbox_id = _claim_inbox_order()
    if inbox_id is not None:
        _process_inbox_order(inbox_id)

    link_id = _claim_catalog_item()
    if link_id is not None:
        _process_catalog_item(link_id)

    return inbox_id is not None or link_id is not None


def _queue_periodic_reconciliation():
    try:
        config = _integration_config()
    except WhatsAppCommerceError:
        return 0
    if not config.get("whatsapp_catalog_sync_enabled"):
        return 0
    now = timezone.now()
    return WhatsAppCatalogSync.objects.filter(
        catalog_linked=True,
        status__in=(WhatsAppCatalogSync.Status.SYNCED, WhatsAppCatalogSync.Status.FAILED),
    ).update(
        status=WhatsAppCatalogSync.Status.PENDING,
        attempt_count=0,
        next_attempt_at=now,
        last_error="",
    )


class Command(BaseCommand):
    help = "Import WhatsApp catalogue orders and synchronise mapped Meta catalogue items."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=5,
            help="Sleep interval when no work is available (1–60 seconds).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one pending WhatsApp order and one catalogue item, then exit.",
        )
        parser.add_argument(
            "--reconcile-minutes",
            type=float,
            default=30,
            help="Queue a full refresh of linked catalogue items at this interval (5–1440 minutes).",
        )

    def handle(self, *args, **options):
        poll_seconds = max(1.0, min(float(options["poll_seconds"]), 60.0))
        once = options["once"]
        reconcile_minutes = max(5.0, min(float(options["reconcile_minutes"]), 1440.0))
        next_reconcile = time.monotonic() + reconcile_minutes * 60
        self.stdout.write("LashPro WhatsApp commerce worker started.")
        try:
            while True:
                close_old_connections()
                try:
                    if not once and time.monotonic() >= next_reconcile:
                        queued = _queue_periodic_reconciliation()
                        logger.info("Queued %s WhatsApp catalogue item(s) for periodic reconciliation.", queued)
                        next_reconcile = time.monotonic() + reconcile_minutes * 60
                    did_work = _work_once()
                finally:
                    close_old_connections()
                if once:
                    return
                if not did_work:
                    time.sleep(poll_seconds)
        except KeyboardInterrupt:
            self.stdout.write("WhatsApp commerce worker stopped.")
