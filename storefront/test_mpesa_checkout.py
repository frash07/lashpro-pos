import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product
from core.models import IntegrationSettings
from payments.models import MpesaStkPush, PaymentTransaction, SalePayment
from payments.mpesa import initiate_stk_push, process_stk_callback
from storefront.models import StorefrontOrder
from storefront.services import transition_storefront_order, expire_due_storefront_orders


@override_settings(STOREFRONT_MPESA_ENABLED=True)
class OnlineMpesaTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="WEB-STK", name="Lash glue", cost_price=100, selling_price=500,
            on_hand=5, active=True,
        )
        self.staff = get_user_model().objects.create_user(
            username="online-stk-owner", password="test-password", role="OWNER", is_staff=True,
        )
        config = IntegrationSettings.get_solo()
        config.set_config({
            "mpesa_environment": "production", "mpesa_consumer_key": "test",
            "mpesa_consumer_secret": "test", "mpesa_shortcode": "123456",
            "mpesa_passkey": "test",
        })
        config.save()

    def checkout(self, stk):
        stk.return_value = {"ResponseCode": "0", "CheckoutRequestID": "online-stk-1"}
        session = self.client.session
        session["storefront_cart"] = {str(self.product.pk): 2}
        session.save()
        response = self.client.post(reverse("storefront:checkout"), {
            "idempotency_key": str(uuid.uuid4()), "full_name": "Test Customer",
            "email": "test@example.com", "phone": "0712345678",
            "accept_terms": "on", "payment_method": "MPESA",
        })
        self.assertEqual(response.status_code, 302)
        order = StorefrontOrder.objects.get()
        self.assertEqual(order.payment_method, "MPESA")
        self.assertEqual(order.status, "PLACED")
        self.assertIsNone(order.sale)
        push = order.mpesa_payment
        self.assertEqual(push.payment_transaction.amount, Decimal("1000"))
        self.assertEqual(push.payment_transaction.status, "UNVERIFIED")
        self.assertEqual(stk.call_count, 1)
        return order, push

    def callback(self, push, code=0, amount=1000):
        return process_stk_callback(callback_token=push.callback_token, payload={
            "Body": {"stkCallback": {
                "CheckoutRequestID": push.checkout_request_id, "ResultCode": code,
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": amount},
                    {"Name": "PhoneNumber", "Value": 254712345678},
                    {"Name": "MpesaReceiptNumber", "Value": "WEBTEST123"},
                ]},
            }},
        })

    @patch("payments.mpesa._stk_request")
    def test_checkout_callback_and_fulfilment(self, stk):
        order, push = self.checkout(stk)
        with self.assertRaises(ValidationError):
            transition_storefront_order(order=order, target_status="CONFIRMED", actor=self.staff)
        self.callback(push)
        self.callback(push)
        order.refresh_from_db()
        self.assertEqual(order.status, "CONFIRMED")
        self.assertEqual(order.mpesa_payment.payment_transaction.status, "SUCCEEDED")
        transition_storefront_order(order=order, target_status="READY", actor=self.staff)
        transition_storefront_order(order=order, target_status="FULFILLED", actor=self.staff)
        order.refresh_from_db()
        self.assertEqual(order.sale.payment_allocations.get().payment_transaction_id, push.payment_transaction_id)
        self.assertEqual(SalePayment.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("3"))

    @patch("payments.mpesa._stk_request")
    def test_pending_retry_does_not_send_duplicate(self, stk):
        order, push = self.checkout(stk)
        self.client.post(reverse("storefront:order-pay", args=[order.access_token]), {"attempt": str(push.pk)})
        self.assertEqual(stk.call_count, 1)

    @patch("payments.mpesa._stk_request")
    def test_failed_retry_sends_new_prompt_once(self, stk):
        order, push = self.checkout(stk)
        self.callback(push, code=1032)
        stk.return_value = {"ResponseCode": "0", "CheckoutRequestID": "online-stk-2"}
        url = reverse("storefront:order-pay", args=[order.access_token])
        self.client.post(url, {"attempt": str(push.pk)})
        self.client.post(url, {"attempt": str(push.pk)})
        self.assertEqual(stk.call_count, 2)
        self.assertEqual(order.mpesa_pushes.count(), 2)

    @patch("payments.mpesa._stk_request")
    def test_late_success_does_not_revive_expired_order(self, stk):
        order, push = self.checkout(stk)
        order.expires_at = timezone.now() - timedelta(seconds=1)
        order.save(update_fields=("expires_at",))
        expire_due_storefront_orders()
        self.callback(push)
        order.refresh_from_db()
        self.assertEqual(order.status, "EXPIRED")
        self.assertEqual(order.mpesa_payment.status, "SUCCEEDED")
        self.assertIsNone(order.sale)

    @patch("payments.mpesa._stk_request")
    def test_wrong_amount_not_paid(self, stk):
        order, push = self.checkout(stk)
        with self.assertRaises(ValidationError):
            self.callback(push, amount=1)
        order.refresh_from_db()
        self.assertEqual(order.status, "PLACED")
        self.assertEqual(order.mpesa_payment.payment_transaction.status, "UNVERIFIED")
