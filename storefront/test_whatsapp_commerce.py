import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from catalog.models import Product
from core.models import IntegrationSettings
from inventory.services import available_stock_for_product

from .models import (
    StorefrontOrder,
    WhatsAppCatalogSync,
    WhatsAppInboundOrder,
)


class WhatsAppWebhookOrderImportTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="WA-CLASSIC-01",
            name="Classic Lash Tray",
            cost_price=Decimal("300.00"),
            selling_price=Decimal("650.00"),
            on_hand=Decimal("5.000"),
            active=True,
        )
        self.app_secret = "meta-app-secret-for-test"
        record = IntegrationSettings.get_solo()
        record.set_config({
            "whatsapp_app_secret": self.app_secret,
            "whatsapp_webhook_verify_token": "test-webhook-verify-token",
            "whatsapp_catalog_id": "catalog-123",
            "whatsapp_business_account_id": "waba-123",
            "whatsapp_phone_number_id": "phone-123",
        })
        record.save(update_fields=("encrypted_config", "updated_at"))

    def _payload(self, *, sku="WA-CLASSIC-01", message_id="wamid.test-001", quantity=2):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-123",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "phone-123"},
                        "contacts": [{
                            "wa_id": "254700111222",
                            "profile": {"name": "WhatsApp Test Customer"},
                        }],
                        "messages": [{
                            "from": "254700111222",
                            "id": message_id,
                            "type": "order",
                            "order": {
                                "catalog_id": "catalog-123",
                                "text": "Please confirm collection.",
                                "product_items": [{
                                    "product_retailer_id": sku,
                                    "quantity": quantity,
                                    "item_price": "1.00",
                                    "currency": "KES",
                                }],
                            },
                        }],
                    },
                }],
            }],
        }

    def _post_webhook(self, payload):
        body = json.dumps(payload).encode("utf-8")
        signature = "sha256=" + hmac.new(
            self.app_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return self.client.post(
            reverse("whatsapp_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    def test_meta_get_verification_returns_the_challenge(self):
        response = self.client.get(reverse("whatsapp_webhook"), {
            "hub.mode": "subscribe",
            "hub.verify_token": "test-webhook-verify-token",
            "hub.challenge": "verification-challenge-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode("utf-8"), "verification-challenge-123")

    def test_invalid_meta_signature_is_rejected(self):
        response = self.client.post(
            reverse("whatsapp_webhook"),
            data=b'{"object":"whatsapp_business_account","entry":[]}',
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=not-a-valid-signature",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(StorefrontOrder.objects.count(), 0)

    def test_catalogue_cart_is_imported_and_reserves_neon_stock(self):
        response = self._post_webhook(self._payload())
        self.assertEqual(response.status_code, 200)

        receipt = WhatsAppInboundOrder.objects.get(message_id="wamid.test-001")
        self.assertEqual(receipt.status, WhatsAppInboundOrder.Status.IMPORTED)
        order = StorefrontOrder.objects.get()
        self.assertEqual(receipt.order_id, order.pk)
        self.assertEqual(order.source_channel, StorefrontOrder.SourceChannel.WHATSAPP)
        self.assertEqual(order.external_order_id, "wamid.test-001")
        self.assertEqual(order.customer_name, "WhatsApp Test Customer")
        self.assertEqual(order.customer_phone, "+254700111222")
        self.assertEqual(order.customer_email, "")
        self.assertEqual(order.total_amount, Decimal("1300.00"))
        self.assertEqual(order.status, StorefrontOrder.Status.PLACED)
        self.assertIsNone(order.sale)
        line = order.lines.get()
        self.assertEqual(line.sku_snapshot, "WA-CLASSIC-01")
        self.assertEqual(line.quantity, 2)
        # The price sent in the WhatsApp order is deliberately ignored.
        self.assertEqual(line.unit_price, Decimal("650.00"))
        self.assertEqual(available_stock_for_product(self.product), Decimal("3.000"))

    def test_duplicate_meta_delivery_does_not_create_a_second_order(self):
        payload = self._payload()
        first = self._post_webhook(payload)
        second = self._post_webhook(payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WhatsAppInboundOrder.objects.count(), 1)
        self.assertEqual(StorefrontOrder.objects.count(), 1)
        self.assertEqual(available_stock_for_product(self.product), Decimal("3.000"))

    def test_unknown_sku_is_recorded_for_staff_review_without_reserving_stock(self):
        response = self._post_webhook(self._payload(sku="SKU-NOT-IN-NEON"))
        self.assertEqual(response.status_code, 200)

        receipt = WhatsAppInboundOrder.objects.get(message_id="wamid.test-001")
        self.assertEqual(receipt.status, WhatsAppInboundOrder.Status.NEEDS_REVIEW)
        self.assertIn("Unknown or inactive", receipt.issue)
        self.assertIsNone(receipt.order)
        self.assertEqual(StorefrontOrder.objects.count(), 0)
        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))

    def test_non_kes_catalogue_order_is_sent_for_review(self):
        payload = self._payload()
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["order"]["product_items"][0]["currency"] = "USD"
        response = self._post_webhook(payload)
        self.assertEqual(response.status_code, 200)

        receipt = WhatsAppInboundOrder.objects.get(message_id="wamid.test-001")
        self.assertEqual(receipt.status, WhatsAppInboundOrder.Status.NEEDS_REVIEW)
        self.assertIn("not priced in KES", receipt.issue)
        self.assertEqual(StorefrontOrder.objects.count(), 0)
        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))

    def test_insufficient_stock_is_sent_for_review_without_partial_order(self):
        response = self._post_webhook(self._payload(quantity=6))
        self.assertEqual(response.status_code, 200)

        receipt = WhatsAppInboundOrder.objects.get(message_id="wamid.test-001")
        self.assertEqual(receipt.status, WhatsAppInboundOrder.Status.NEEDS_REVIEW)
        self.assertIn("Only", receipt.issue)
        self.assertEqual(StorefrontOrder.objects.count(), 0)
        self.assertEqual(available_stock_for_product(self.product), Decimal("5.000"))


class WhatsAppCatalogueSyncTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="WA-SYNC-01",
            name="Hybrid Lash Tray",
            cost_price=Decimal("400.00"),
            selling_price=Decimal("875.50"),
            on_hand=Decimal("8.000"),
            active=True,
        )
        self.product.image = "catalog/hybrid-lash-tray.jpg"
        self.product.save(update_fields=("image",))
        settings_record = IntegrationSettings.get_solo()
        settings_record.set_config({
            "whatsapp_access_token": "test-access-token",
            "whatsapp_catalog_id": "catalog-123",
            "whatsapp_catalog_sync_enabled": True,
        })
        settings_record.save(update_fields=("encrypted_config", "updated_at"))

    @patch("storefront.whatsapp._graph_post", return_value={"id": "meta-item-456"})
    @patch("storefront.whatsapp._product_public_image", return_value="https://cdn.example.test/hybrid.jpg")
    def test_sync_publishes_neon_price_and_available_inventory(self, image_url, graph_post):
        record = WhatsAppCatalogSync.objects.create(
            product=self.product,
            retailer_id=self.product.sku,
        )

        from .whatsapp import sync_catalog_record
        synced = sync_catalog_record(record.pk)

        self.assertEqual(synced.status, WhatsAppCatalogSync.Status.SYNCED)
        self.assertEqual(synced.remote_product_id, "meta-item-456")
        self.assertEqual(synced.attempts, 1)
        self.assertEqual(graph_post.call_count, 2)
        create_payload = graph_post.call_args_list[0].kwargs["data"]
        inventory_payload = graph_post.call_args_list[1].kwargs["data"]
        self.assertEqual(create_payload["retailer_id"], "WA-SYNC-01")
        self.assertEqual(create_payload["price"], 87550)
        self.assertEqual(create_payload["currency"], "KES")
        self.assertNotIn("inventory", create_payload)
        self.assertEqual(create_payload["availability"], "in stock")
        self.assertEqual(inventory_payload, {"inventory": 8})
