import logging
import uuid
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalog.models import Product, WhatsAppCatalogSync
from core.models import IntegrationSettings
from customers.models import Customer
from inventory.services import available_stock_for_product
from storefront.models import StorefrontOrder, WhatsAppOrderInbox
from storefront.services import create_storefront_order

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")
MAX_ORDER_LINES = 25
MAX_LINE_QUANTITY = 99


class WhatsAppCommerceError(Exception):
    """An integration error safe to display to a LashPro administrator."""


def _integration_config():
    record = IntegrationSettings.objects.filter(pk=1).first()
    if not record:
        raise WhatsAppCommerceError("WhatsApp integration settings have not been saved.")
    try:
        config = record.get_config()
    except RuntimeError as exc:
        raise WhatsAppCommerceError("WhatsApp credentials could not be decrypted. Check the stable Django secret key.") from exc
    required = ("whatsapp_access_token", "whatsapp_phone_number_id", "whatsapp_catalog_id")
    missing = [key for key in required if not (config.get(key) or "").strip()]
    if missing:
        raise WhatsAppCommerceError("Complete the WhatsApp access token, phone number ID and Meta catalogue ID in API Integrations.")
    return config


def queue_existing_whatsapp_catalog_sync():
    """Create unlinked mapping rows and queue already-mapped items; never guess existing Meta IDs."""
    created = 0
    for product in Product.objects.only("pk").iterator():
        _, was_created = WhatsAppCatalogSync.objects.get_or_create(
            product_id=product.pk,
            defaults={"status": WhatsAppCatalogSync.Status.UNLINKED},
        )
        created += int(was_created)

    try:
        config = _integration_config()
    except WhatsAppCommerceError:
        config = {}
    enabled = bool(config.get("whatsapp_catalog_sync_enabled"))
    queued = 0
    if enabled:
        queued = WhatsAppCatalogSync.objects.filter(catalog_linked=True).update(
            status=WhatsAppCatalogSync.Status.PENDING,
            attempt_count=0,
            next_attempt_at=timezone.now(),
            last_error="",
        )
    return created, queued


def _graph_post(config, path, payload):
    version = (config.get("whatsapp_api_version") or "v27.0").strip()
    if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
        raise WhatsAppCommerceError("The configured Meta Graph API version is invalid.")
    url = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    request = Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['whatsapp_access_token']}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            import json
            return json.loads(response.read(65536).decode("utf-8"))
    except HTTPError as exc:
        try:
            import json
            body = json.loads(exc.read(8192).decode("utf-8", errors="replace"))
            message = body.get("error", {}).get("message") or "Meta rejected the catalogue update."
            code = body.get("error", {}).get("code")
            detail = f"Meta Graph API error {code}: {message}" if code else f"Meta Graph API error: {message}"
        except Exception:
            detail = f"Meta Graph API returned HTTP {exc.code}."
        raise WhatsAppCommerceError(detail[:800]) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WhatsAppCommerceError(f"Could not reach Meta Graph API: {exc}") from exc
    except ValueError as exc:
        raise WhatsAppCommerceError("Meta returned an unreadable catalogue response.") from exc


def sync_whatsapp_catalog_item(link_id):
    """Publish one linked product using sellable stock and the current LashPro price."""
    link = WhatsAppCatalogSync.objects.select_related("product").get(pk=link_id)
    config = _integration_config()
    if not config.get("whatsapp_catalog_sync_enabled"):
        raise WhatsAppCommerceError("Automatic WhatsApp catalogue synchronisation is disabled in API Integrations.")
    if not link.catalog_linked or not (link.retailer_id or "").strip():
        raise WhatsAppCommerceError("This product has no verified WhatsApp catalogue Content ID / retailer ID.")

    product = link.product
    if not product.image:
        raise WhatsAppCommerceError(f"Upload a public product image for {product.name} before synchronising it.")
    try:
        image_url = product.image.url
    except (ValueError, OSError) as exc:
        raise WhatsAppCommerceError(f"The product image for {product.name} is unavailable.") from exc
    if not image_url.startswith(("https://", "http://")):
        raise WhatsAppCommerceError(f"The product image for {product.name} is not hosted at a public HTTPS URL.")

    available = available_stock_for_product(product)
    inventory = max(0, int(available))
    if not product.active:
        availability = "discontinued"
    elif inventory > 0:
        availability = "in stock"
    else:
        availability = "out of stock"

    try:
        price_minor_units = int(Decimal(product.selling_price).quantize(CENT) * 100)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WhatsAppCommerceError(f"The selling price for {product.name} is invalid.") from exc
    if price_minor_units < 0:
        raise WhatsAppCommerceError(f"The selling price for {product.name} cannot be negative.")

    payload = {
        "retailer_id": link.retailer_id,
        "name": product.name[:200],
        "description": f"LashPro professional beauty product: {product.name}"[:5000],
        "category": "Health & Beauty",
        "brand": "LashPro",
        "condition": "new",
        "currency": "KES",
        "price": price_minor_units,
        "availability": availability,
        "inventory": inventory,
        "image_url": image_url,
    }

    catalog_id = config["whatsapp_catalog_id"].strip()
    if link.meta_product_item_id:
        response = _graph_post(config, link.meta_product_item_id, payload)
    else:
        payload["allow_upsert"] = "true" if link.allow_upsert else "false"
        response = _graph_post(config, f"{catalog_id}/products", payload)

    meta_id = str(response.get("id") or link.meta_product_item_id or "").strip()
    link.meta_product_item_id = meta_id
    link.status = WhatsAppCatalogSync.Status.SYNCED
    link.attempt_count = 0
    link.next_attempt_at = timezone.now()
    link.last_error = ""
    link.last_synced_at = timezone.now()
    link.save(update_fields=(
        "meta_product_item_id", "status", "attempt_count", "next_attempt_at",
        "last_error", "last_synced_at", "updated_at",
    ))
    return link


def _normalise_whatsapp_phone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits.startswith(("7", "1")):
        digits = "254" + digits
    if len(digits) < 10 or len(digits) > 15:
        raise ValidationError({"customer_phone": "WhatsApp did not provide a valid customer phone number."})
    return "+" + digits


def _parse_order_items(inbox, config):
    payload = inbox.order_payload if isinstance(inbox.order_payload, dict) else {}
    order = payload.get("order", payload)
    catalog_id = str(order.get("catalog_id") or inbox.catalog_id or "").strip()
    if catalog_id != str(config.get("whatsapp_catalog_id") or "").strip():
        raise ValidationError({"order": "This WhatsApp order came from a different catalogue. Review it before importing."})

    lines = order.get("product_items")
    if not isinstance(lines, list) or not lines:
        raise ValidationError({"order": "The WhatsApp order contains no products."})
    if len(lines) > MAX_ORDER_LINES:
        raise ValidationError({"order": f"WhatsApp orders can contain at most {MAX_ORDER_LINES} different product lines."})

    retailer_ids = [str(line.get("product_retailer_id") or "").strip() for line in lines]
    if any(not retailer_id for retailer_id in retailer_ids):
        raise ValidationError({"order": "A WhatsApp order line has no product Content ID."})

    links = {
        link.retailer_id: link
        for link in WhatsAppCatalogSync.objects.select_related("product").filter(
            retailer_id__in=retailer_ids,
            catalog_linked=True,
        )
    }
    if len(links) != len(set(retailer_ids)):
        missing = sorted(set(retailer_ids) - set(links))
        raise ValidationError({"order": "Unmapped WhatsApp catalogue item(s): " + ", ".join(missing[:5]) + ". Link each Meta Content ID to a LashPro SKU before retrying."})

    items = {}
    for line in lines:
        retailer_id = str(line["product_retailer_id"]).strip()
        link = links[retailer_id]
        product = link.product
        if not product.active:
            raise ValidationError({"order": f"{product.name} is inactive in LashPro and cannot be ordered."})
        try:
            quantity_decimal = Decimal(str(line.get("quantity", "")))
            quantity = int(quantity_decimal)
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            raise ValidationError({"order": f"The quantity for {product.name} is invalid."}) from None
        if quantity_decimal != quantity or quantity < 1 or quantity > MAX_LINE_QUANTITY:
            raise ValidationError({"order": f"The quantity for {product.name} must be between 1 and {MAX_LINE_QUANTITY} whole units."})

        currency = str(line.get("currency") or "").upper()
        if currency != "KES":
            raise ValidationError({"order": f"The WhatsApp catalogue price for {product.name} is not in KES."})
        try:
            meta_price = Decimal(str(line.get("item_price", ""))).quantize(CENT)
            lashpro_price = Decimal(product.selling_price).quantize(CENT)
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError({"order": f"The WhatsApp catalogue price for {product.name} is invalid."}) from None
        if meta_price != lashpro_price:
            raise ValidationError({
                "order": f"The catalogue price for {product.name} (KSh {meta_price:,.2f}) differs from LashPro (KSh {lashpro_price:,.2f}). Update/sync the catalogue, then retry the order."
            })

        product_key = str(product.pk)
        items[product_key] = items.get(product_key, 0) + quantity
        if items[product_key] > MAX_LINE_QUANTITY:
            raise ValidationError({"order": f"The total quantity for {product.name} exceeds {MAX_LINE_QUANTITY}."})

    return items, str(order.get("text") or "").strip()[:500]


@transaction.atomic
def import_whatsapp_order(inbox_id):
    """Import one Meta order once, using the same atomic stock reservation service as web checkout."""
    inbox = WhatsAppOrderInbox.objects.select_for_update().get(pk=inbox_id)
    if inbox.status == WhatsAppOrderInbox.Status.IMPORTED and inbox.order_id:
        return inbox.order

    config = _integration_config()
    items, customer_note = _parse_order_items(inbox, config)
    phone = _normalise_whatsapp_phone(inbox.sender_phone)
    name = " ".join(str(inbox.customer_name or "").split())[:100] or "WhatsApp customer"

    existing_customer = Customer.objects.filter(phone=phone).order_by("pk").first()
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"lashpro:whatsapp-order:{inbox.message_id}")
    order = create_storefront_order(
        items=items,
        customer_name=name,
        customer_email="",
        customer_phone=phone,
        notes=customer_note,
        customer=existing_customer,
        idempotency_key=key,
        source_channel=StorefrontOrder.SourceChannel.WHATSAPP,
        external_reference=inbox.message_id,
    )
    inbox.order = order
    inbox.status = WhatsAppOrderInbox.Status.IMPORTED
    inbox.attempt_count = 0
    inbox.last_error = ""
    inbox.processed_at = timezone.now()
    inbox.save(update_fields=(
        "order", "status", "attempt_count", "last_error", "processed_at",
    ))
    return order
