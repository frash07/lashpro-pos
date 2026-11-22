import hashlib
import hmac
import json
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, WhatsAppCatalogSync
from core.models import IntegrationSettings
from core.whatsapp_commerce import import_whatsapp_order
from storefront.models import StorefrontOrder, StorefrontStockReservation, WhatsAppOrderInbox


class WhatsAppWebhookTests(TestCase):
    def setUp(self):
        self.config = {
            "whatsapp_access_token": "test-access-token",
            "whatsapp_phone_number_id": "123456789",
            "whatsapp_business_account_id": "987654321",
            "whatsapp_catalog_id": "555666777",
            "whatsapp_app_secret": "test-app-secret",
            "whatsapp_webhook_verify_token": "test-verify-token",
            "whatsapp_catalog_sync_enabled": True,
            "whatsapp_api_version": "v27.0",
        }
        record = IntegrationSettings.get_solo()
        record.set_config(self.config)
        record.save(update_fields=("encrypted_config", "updated_at"))

    def _signed_post(self, payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(
            self.config["whatsapp_app_secret"].encode("utf-8"),
            raw,
            hashlib.sha256,
        ).hexdigest()
        return self.client.post(
            "/webhooks/whatsapp/",
            data=raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    def _payload(self, message_id="wamid.order-001"):
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": self.config["whatsapp_business_account_id"],
                "changes": [{
                    "field": "messages",
                    "value": {
                        "contacts": [{
                            "wa_id": "254712345678",
                            "profile": {"name": "Asha Client"},
                        }],
                        "messages": [{
                            "from": "254712345678",
                            "id": message_id,
                            "timestamp": "1790000000",
                            "type": "order",
                            "order": {
                                "catalog_id": self.config["whatsapp_catalog_id"],
                                "text": "Please deliver tomorrow.",
                                "product_items": [{
                                    "product_retailer_id": "LP-001",
                                    "quantity": "2",
                                    "item_price": "650.00",
                                    "currency": "KES",
                                }],
                            },
                        }],
                    },
                }],
            }],
        }

    def test_meta_get_verification_returns_the_challenge(self):
        response = self.client.get(
            "/webhooks/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": self.config["whatsapp_webhook_verify_token"],
                "hub.challenge": "test-challenge-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "test-challenge-123")

    def test_invalid_meta_webhook_signature_is_rejected(self):
        response = self.client.post(
            "/webhooks/whatsapp/",
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WhatsAppOrderInbox.objects.count(), 0)

    def test_catalogue_order_webhook_is_persisted_and_deduplicated(self):
        first = self._signed_post(self._payload())
        second = self._signed_post(self._payload())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WhatsAppOrderInbox.objects.count(), 1)
        inbox = WhatsAppOrderInbox.objects.get()
        self.assertEqual(inbox.sender_phone, "254712345678")
        self.assertEqual(inbox.customer_name, "Asha Client")
        self.assertEqual(inbox.catalog_id, self.config["whatsapp_catalog_id"])
        self.assertEqual(inbox.status, WhatsAppOrderInbox.Status.PENDING)


class WhatsAppOrderImportTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="LP-001",
            name="Lash Adhesive",
            cost_price=Decimal("300.00"),
            selling_price=Decimal("650.00"),
            on_hand=Decimal("5.000"),
            active=True,
        )
        WhatsAppCatalogSync.objects.create(
            product=self.product,
            retailer_id="LP-001",
            catalog_linked=True,
            allow_upsert=False,
            status=WhatsAppCatalogSync.Status.SYNCED,
        )
        self.config = {
            "whatsapp_access_token": "test-access-token",
            "whatsapp_phone_number_id": "123456789",
            "whatsapp_catalog_id": "555666777",
            "whatsapp_catalog_sync_enabled": True,
        }
        record = IntegrationSettings.get_solo()
        record.set_config(self.config)
        record.save(update_fields=("encrypted_config", "updated_at"))
        self.inbox = WhatsAppOrderInbox.objects.create(
            message_id="wamid.order-import-001",
            sender_phone="254712345678",
            customer_name="Asha Client",
            catalog_id=self.config["whatsapp_catalog_id"],
            order_payload={
                "catalog_id": self.config["whatsapp_catalog_id"],
                "text": "Please deliver tomorrow.",
                "product_items": [{
                    "product_retailer_id": "LP-001",
                    "quantity": "2",
                    "item_price": "650.00",
                    "currency": "KES",
                }],
            },
        )

    def test_whatsapp_order_uses_the_existing_stock_reservation_flow(self):
        order = import_whatsapp_order(self.inbox.pk)
        self.assertEqual(order.source_channel, StorefrontOrder.SourceChannel.WHATSAPP)
        self.assertEqual(order.external_reference, self.inbox.message_id)
        self.assertEqual(order.customer_name, "Asha Client")
        self.assertEqual(order.customer_phone, "+254712345678")
        self.assertEqual(order.customer_email, "")
        self.assertEqual(order.status, StorefrontOrder.Status.PLACED)
        self.assertEqual(order.total_amount, Decimal("1300.00"))
        self.assertIsNone(order.sale_id)
        reservation = StorefrontStockReservation.objects.get(order_line__order=order)
        self.assertEqual(reservation.quantity, Decimal("2.000"))
        self.assertEqual(reservation.status, StorefrontStockReservation.Status.ACTIVE)
        self.inbox.refresh_from_db()
        self.assertEqual(self.inbox.status, WhatsAppOrderInbox.Status.IMPORTED)
        self.assertEqual(self.inbox.order_id, order.pk)

    def test_reimporting_the_same_message_returns_the_original_order(self):
        first = import_whatsapp_order(self.inbox.pk)
        second = import_whatsapp_order(self.inbox.pk)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StorefrontOrder.objects.filter(source_channel="WHATSAPP").count(), 1)
        self.assertEqual(StorefrontStockReservation.objects.filter(order_line__order=first).count(), 1)

    def test_price_mismatch_does_not_create_an_order_or_reserve_stock(self):
        payload = dict(self.inbox.order_payload)
        payload["product_items"] = [dict(payload["product_items"][0], item_price="600.00")]
        self.inbox.order_payload = payload
        self.inbox.save(update_fields=("order_payload",))
        with self.assertRaises(Exception):
            import_whatsapp_order(self.inbox.pk)
        self.assertEqual(StorefrontOrder.objects.count(), 0)
        self.assertEqual(StorefrontStockReservation.objects.count(), 0)
