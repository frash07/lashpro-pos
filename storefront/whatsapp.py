import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from catalog.models import Product
from core.models import IntegrationSettings
from customers.models import Customer
from inventory.services import available_stock_for_product

from .models import (
    StorefrontOrder,
    WhatsAppCatalogSync,
    WhatsAppInboundOrder,
)
from .services import create_storefront_order

logger = logging.getLogger(__name__)
MAX_ORDER_LINES = 25
MAX_ORDER_QUANTITY = 99
CENT = Decimal("0.01")


def _integration_config():
    return IntegrationSettings.get_solo().get_config()


def verify_webhook_signature(*, body, signature, app_secret):
    if not (body and signature and app_secret):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _graph_post(*, version, path, token, data, timeout=8):
    url = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(16384).decode("utf-8", errors="replace")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = ""
        raise RuntimeError(
            f"Meta Graph API returned HTTP {exc.code}"
            + (f": {detail[:300]}" if detail else ".")
        ) from None


def _product_public_image(product):
    try:
        image_url = product.image.url if product.image else ""
    except (ValueError, OSError):
        image_url = ""
    if not image_url.startswith(("https://", "http://")):
        return ""
    return image_url


def _catalog_payload(product, retailer_id, *, require_image=True):
    image_url = _product_public_image(product)
    if require_image and not image_url:
        raise ValueError(
            f"{retailer_id}: upload a public product image before publishing it to WhatsApp."
        )

    if product.active:
        available = max(Decimal(available_stock_for_product(product)), Decimal("0"))
        inventory = int(available)
        availability = "in stock" if inventory > 0 else "out of stock"
        visibility = "published"
    else:
        inventory = 0
        availability = "discontinued"
        visibility = "staging"

    storefront_base = getattr(
        settings, "STOREFRONT_BASE_URL", "https://lashproke.cc"
    ).rstrip("/")
    product_link = storefront_base + "/?" + urllib.parse.urlencode({
        "kind": "products",
        "q": product.sku,
    })
    try:
        price = int(
            (Decimal(product.selling_price).quantize(CENT) * 100).to_integral_value()
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{retailer_id}: selling price is invalid.") from None

    payload = {
        "retailer_id": retailer_id,
        "name": product.name[:200],
        "description": f"{product.name} · LashPro SKU {retailer_id}"[:5000],
        "price": price,
        "currency": "KES",
        "availability": availability,
        "inventory": inventory,
        "condition": "new",
        "visibility": visibility,
        "image_url": image_url,
        "url": product_link,
        "brand": "LashPro",
        "product_type": "Beauty & personal care",
    }
    if image_url:
        payload["image_url"] = image_url
    return payload


def sync_catalog_record(record_id):
    """Publish one outbox record to Meta; failures remain visible and retryable."""
    record = WhatsAppCatalogSync.objects.select_related("product").get(pk=record_id)
    config = _integration_config()
    token = (config.get("whatsapp_access_token") or "").strip()
    catalog_id = (config.get("whatsapp_catalog_id") or "").strip()
    if not config.get("whatsapp_catalog_sync_enabled") or not token or not catalog_id:
        return record

    record.attempts += 1
    record.status = WhatsAppCatalogSync.Status.PENDING
    record.last_error = ""
    record.save(update_fields=("attempts", "status", "last_error", "updated_at"))
    try:
        product = record.product
        if product is None:
            raise ValueError(f"{record.retailer_id}: the linked LashPro product no longer exists.")
        is_update = bool(record.remote_product_id)
        payload = _catalog_payload(
            product, record.retailer_id, require_image=not is_update
        )
        inventory = payload.pop("inventory")
        version = (config.get("whatsapp_api_version") or "v27.0").strip()
        endpoint = record.remote_product_id if is_update else f"{catalog_id}/products"
        if is_update:
            # retailer_id is an identifier on create, but Meta treats it as
            # internal/read-only in the ProductItem update schema.
            payload.pop("retailer_id", None)
        else:
            # Meta accepts price/availability at item creation; inventory is
            # applied to the returned ProductItem ID in a second update call.
            payload["allow_upsert"] = "true"
        result = _graph_post(
            version=version,
            path=endpoint,
            token=token,
            data=payload,
        )
        remote_id = str(result.get("id") or record.remote_product_id or "")
        if not remote_id and result.get("success") is not True:
            raise RuntimeError("Meta did not return a catalogue item ID or success status.")
        if not is_update:
            # Persist the created Meta item ID before the stock update call.
            # If the second call fails, a retry updates this item rather than
            # creating a duplicate catalogue entry.
            record.remote_product_id = remote_id
            record.save(update_fields=("remote_product_id", "updated_at"))
            _graph_post(
                version=version,
                path=remote_id,
                token=token,
                data={"inventory": inventory},
            )
    except Exception as exc:
        record.status = WhatsAppCatalogSync.Status.FAILED
        record.last_error = str(exc)[:2000]
        record.save(update_fields=("status", "last_error", "updated_at"))
        logger.warning(
            "WhatsApp catalogue sync failed for SKU %s: %s",
            record.retailer_id,
            record.last_error,
        )
        return record

    record.remote_product_id = remote_id
    record.status = WhatsAppCatalogSync.Status.SYNCED
    record.last_error = ""
    record.last_synced_at = timezone.now()
    record.save(update_fields=(
        "remote_product_id", "status", "last_error", "last_synced_at", "updated_at"
    ))
    return record


def enqueue_product_catalog_sync(product_id):
    """Create/update the product's durable Meta catalogue outbox row."""
    config = _integration_config()
    if not (
        config.get("whatsapp_catalog_sync_enabled")
        and config.get("whatsapp_access_token")
        and config.get("whatsapp_catalog_id")
    ):
        return None
    try:
        product = Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        return None

    retailer_id = (product.whatsapp_retailer_id or product.sku).strip()
    record = WhatsAppCatalogSync.objects.filter(product=product).first()
    if record:
        if record.remote_product_id and record.retailer_id != retailer_id:
            record.status = WhatsAppCatalogSync.Status.FAILED
            record.last_error = (
                "The Meta retailer ID cannot be changed after publication. "
                "Keep the original Content ID or remove/reconcile the Meta item manually."
            )
            record.save(update_fields=("status", "last_error", "updated_at"))
            return record
        record.retailer_id = retailer_id
        record.status = WhatsAppCatalogSync.Status.PENDING
        record.last_error = ""
        record.save(update_fields=("retailer_id", "status", "last_error", "updated_at"))
    else:
        record, _ = WhatsAppCatalogSync.objects.update_or_create(
            retailer_id=retailer_id,
            defaults={
                "product": product,
                "status": WhatsAppCatalogSync.Status.PENDING,
                "last_error": "",
            },
        )
    # Product and reservation signals only enqueue work. A scheduled worker
    # performs network I/O outside customer checkout and POS stock transactions.
    return record


def retry_catalog_sync(*, all_products=False):
    """Dispatch pending changes and optionally enqueue every product for a full sync."""
    config = _integration_config()
    if not (
        config.get("whatsapp_catalog_sync_enabled")
        and config.get("whatsapp_access_token")
        and config.get("whatsapp_catalog_id")
    ):
        return
    if all_products:
        for product_id in Product.objects.order_by("pk").values_list("pk", flat=True).iterator():
            try:
                enqueue_product_catalog_sync(product_id)
            except Exception:
                logger.exception("Could not queue WhatsApp catalogue sync for product %s.", product_id)
    pending_ids = list(
        WhatsAppCatalogSync.objects.filter(
            status__in=(WhatsAppCatalogSync.Status.PENDING, WhatsAppCatalogSync.Status.FAILED)
        ).order_by("updated_at").values_list("pk", flat=True)[:250]
    )
    for record_id in pending_ids:
        try:
            sync_catalog_record(record_id)
        except Exception:
            logger.exception("Could not retry WhatsApp catalogue record %s.", record_id)


def _mark_receipt_for_review(receipt, issue):
    receipt.status = WhatsAppInboundOrder.Status.NEEDS_REVIEW
    receipt.issue = str(issue)[:500]
    receipt.save(update_fields=("status", "issue", "updated_at"))
    return receipt


def _normalise_order_items(order_data):
    items = order_data.get("product_items")
    if not isinstance(items, list) or not items:
        raise ValidationError("The WhatsApp order does not contain product items.")
    if len(items) > MAX_ORDER_LINES:
        raise ValidationError(f"A WhatsApp order can contain at most {MAX_ORDER_LINES} product lines.")

    quantities_by_sku = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("The WhatsApp order contains an invalid product line.")
        sku = str(item.get("product_retailer_id") or "").strip()
        try:
            quantity_value = Decimal(str(item.get("quantity", "")))
            quantity = int(quantity_value)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            raise ValidationError("A WhatsApp order contains an invalid quantity.") from None
        currency = str(item.get("currency") or "").strip().upper()
        if currency != "KES":
            raise ValidationError("The WhatsApp catalogue order is not priced in KES; send it for staff review.")
        if not sku or quantity_value != quantity or quantity < 1 or quantity > MAX_ORDER_QUANTITY:
            raise ValidationError("WhatsApp quantities must be whole numbers between 1 and 99.")
        quantities_by_sku[sku] = quantities_by_sku.get(sku, 0) + quantity
        if quantities_by_sku[sku] > MAX_ORDER_QUANTITY:
            raise ValidationError(f"The requested quantity for SKU {sku} exceeds 99.")
    return quantities_by_sku


@transaction.atomic
def import_whatsapp_order(message, contacts, *, configured_catalog_id):
    """Convert an inbound Meta order message into a normal, stock-reserved LashPro order."""
    message_id = str(message.get("id") or "").strip()
    raw_sender = str(message.get("from") or "").strip()
    sender_id = "".join(ch for ch in raw_sender if ch.isdigit())
    if not 8 <= len(sender_id) <= 15:
        sender_id = ""
    order_data = message.get("order")
    if not message_id or not isinstance(order_data, dict):
        return None

    profile_name = ""
    for contact in contacts or []:
        if (
            str(contact.get("wa_id") or "") == sender_id
            or (
                not sender_id
                and str(contact.get("user_id") or "") == str(message.get("from_user_id") or "")
            )
        ):
            profile_name = str((contact.get("profile") or {}).get("name") or "").strip()
            break

    if not sender_id:
        user_id = str(message.get("from_user_id") or raw_sender).strip()
        if not user_id:
            return None
        receipt, created = WhatsAppInboundOrder.objects.get_or_create(
            message_id=message_id,
            defaults={
                "sender_id": ("UID:" + user_id)[:32],
                "customer_name": (profile_name or "WhatsApp customer")[:100],
                "catalog_id": str(order_data.get("catalog_id") or "").strip(),
                "status": WhatsAppInboundOrder.Status.NEEDS_REVIEW,
            },
        )
        if not created:
            return receipt
        return _mark_receipt_for_review(
            receipt,
            "Meta did not provide a phone-number sender ID. Staff must match this WhatsApp user and enter the order manually.",
        )
    customer_name = (profile_name or f"WhatsApp customer {sender_id}")[:100]
    catalog_id = str(order_data.get("catalog_id") or "").strip()

    receipt, created = WhatsAppInboundOrder.objects.get_or_create(
        message_id=message_id,
        defaults={
            "sender_id": sender_id,
            "customer_name": customer_name,
            "catalog_id": catalog_id,
            "status": WhatsAppInboundOrder.Status.NEEDS_REVIEW,
        },
    )
    if not created:
        return receipt

    if configured_catalog_id and catalog_id != str(configured_catalog_id):
        return _mark_receipt_for_review(receipt, "The order came from an unexpected WhatsApp catalogue.")

    try:
        quantities_by_sku = _normalise_order_items(order_data)
    except ValidationError as exc:
        return _mark_receipt_for_review(receipt, " ".join(exc.messages))

    matched_products = Product.objects.filter(active=True).filter(
        Q(sku__in=list(quantities_by_sku))
        | Q(whatsapp_retailer_id__in=list(quantities_by_sku))
    )
    products = {}
    ambiguous = set()
    for product in matched_products:
        for retailer_id in (product.sku, product.whatsapp_retailer_id):
            if not retailer_id or retailer_id not in quantities_by_sku:
                continue
            if retailer_id in products and products[retailer_id].pk != product.pk:
                ambiguous.add(retailer_id)
            else:
                products[retailer_id] = product
    if ambiguous:
        return _mark_receipt_for_review(
            receipt, "Ambiguous LashPro product mapping(s): " + ", ".join(sorted(ambiguous)[:8])
        )
    missing = sorted(set(quantities_by_sku) - set(products))
    if missing:
        return _mark_receipt_for_review(
            receipt, "Unknown or inactive LashPro catalogue ID(s): " + ", ".join(missing[:8])
        )

    cart = {}
    for retailer_id, quantity in quantities_by_sku.items():
        product_key = str(products[retailer_id].pk)
        cart[product_key] = cart.get(product_key, 0) + quantity
        if cart[product_key] > MAX_ORDER_QUANTITY:
            return _mark_receipt_for_review(
                receipt, "The combined quantity for a LashPro product exceeds 99."
            )
    whatsapp_note = str(order_data.get("text") or "").strip()[:350]
    notes = "WhatsApp catalogue order"
    if whatsapp_note:
        notes += f" — Customer note: {whatsapp_note}"
    try:
        order = create_storefront_order(
            items=cart,
            customer_name=customer_name,
            customer_email="",
            customer_phone="+" + sender_id,
            notes=notes[:500],
            customer=Customer.objects.filter(phone__in=(sender_id, "+" + sender_id)).first(),
            idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f"lashpro:whatsapp:{message_id}"),
            source_channel=StorefrontOrder.SourceChannel.WHATSAPP,
            external_order_id=message_id,
        )
    except ValidationError as exc:
        return _mark_receipt_for_review(receipt, " ".join(exc.messages))

    receipt.order = order
    receipt.status = WhatsAppInboundOrder.Status.IMPORTED
    receipt.issue = ""
    receipt.save(update_fields=("order", "status", "issue", "updated_at"))
    return receipt


def process_whatsapp_webhook(payload, *, configured_catalog_id):
    """Process inbound product-cart order messages; ignore ordinary chat messages."""
    imported = 0
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            if change.get("field") != "messages":
                continue
            messages = value.get("messages") or []
            contacts = value.get("contacts") or []
            for message in messages:
                if message.get("type") != "order":
                    continue
                receipt = import_whatsapp_order(
                    message,
                    contacts,
                    configured_catalog_id=configured_catalog_id,
                )
                if receipt and receipt.status == WhatsAppInboundOrder.Status.IMPORTED:
                    imported += 1
    return imported
