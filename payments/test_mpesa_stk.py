import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from accounts.models import User
from catalog.models import Service
from core.models import IntegrationSettings
from payments.models import MpesaStkPush, PaymentTransaction, SalePayment
from payments.mpesa import (
    DarajaOutcomeUnknown, _read_json_response, initiate_stk_push,
    normalize_mpesa_phone, process_stk_callback,
)
from sales.forms import PaymentForm
from sales.models import Sale, SaleLine
import urllib.error
import urllib.request


class MpesaPhoneNormalizationTests(SimpleTestCase):
    def test_accepts_common_kenyan_phone_formats(self):
        self.assertEqual(normalize_mpesa_phone("0712 345 678"), "254712345678")
        self.assertEqual(normalize_mpesa_phone("+254 712 345 678"), "254712345678")
        self.assertEqual(normalize_mpesa_phone("712345678"), "254712345678")

    def test_rejects_non_kenyan_or_invalid_numbers(self):
        with self.assertRaises(ValidationError):
            normalize_mpesa_phone("0201234567")

    def test_temporary_http_error_from_stk_post_is_outcome_unknown(self):
        request = urllib.request.Request(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            data=b"{}",
            method="POST",
        )
        error = urllib.error.HTTPError(request.full_url, 500, "server error", {}, None)
        with patch("payments.mpesa.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(DarajaOutcomeUnknown):
                _read_json_response(request)

    def test_pos_payment_form_rejects_manual_mpesa_reference(self):
        form = PaymentForm(data={
            "method": "MPESA",
            "amount": "1500.00",
            "reference": "QWE1234567",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("STK Push", str(form.errors))


class MpesaStkCallbackTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="stk-owner",
            password="test-password",
            role=User.Role.OWNER,
        )
        self.service = Service.objects.create(
            name="STK test set",
            duration_minutes=60,
            price=Decimal("1500.00"),
            active=True,
        )
        self.sale = Sale.objects.create(cashier=self.owner)
        SaleLine.from_service(sale=self.sale, service=self.service).save()
        self.sale.status = Sale.Status.COMPLETED
        self.sale.save(update_fields=("status",))
        self.config = IntegrationSettings.get_solo()
        self.config.set_config({
            "mpesa_environment": "sandbox",
            "mpesa_consumer_key": "consumer-key",
            "mpesa_consumer_secret": "consumer-secret",
            "mpesa_shortcode": "174379",
            "mpesa_passkey": "passkey",
            "mpesa_transaction_type": "CustomerPayBillOnline",
        })
        self.config.save()

    @patch("payments.mpesa._stk_request")
    def test_stk_initiation_is_idempotent(self, stk_request):
        stk_request.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-request",
            "CheckoutRequestID": "ws_CO_123",
            "CustomerMessage": "Success. Request accepted for processing",
        }
        key = uuid.uuid4()
        first = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/payments/mpesa/stk/callback/token/",
            callback_token="first-callback-token",
            idempotency_key=key,
            actor=self.owner,
        )
        second = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/payments/mpesa/stk/callback/other/",
            callback_token="second-callback-token",
            idempotency_key=key,
            actor=self.owner,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(stk_request.call_count, 1)
        self.assertEqual(PaymentTransaction.objects.filter(method="MPESA").count(), 1)
        self.assertEqual(SalePayment.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(first.status, MpesaStkPush.Status.PENDING)

    @patch("payments.mpesa._stk_request")
    def test_success_callback_confirms_payment_and_is_idempotent(self, stk_request):
        stk_request.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-request",
            "CheckoutRequestID": "ws_CO_success",
        }
        push = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/callback/",
            callback_token="callback-success",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        payload = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": "ws_CO_success",
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 1500},
                            {"Name": "MpesaReceiptNumber", "Value": "QWE1234567"},
                            {"Name": "PhoneNumber", "Value": 254712345678},
                        ]
                    },
                }
            }
        }

        first = process_stk_callback(callback_token="callback-success", payload=payload)
        second = process_stk_callback(callback_token="callback-success", payload=payload)
        push.refresh_from_db()
        payment = push.payment_transaction
        payment.refresh_from_db()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(push.status, MpesaStkPush.Status.SUCCEEDED)
        self.assertEqual(payment.status, PaymentTransaction.Status.SUCCEEDED)
        self.assertTrue(payment.reference.startswith("STK-"))
        self.assertEqual(payment.display_reference, "••••4567")

    @patch("payments.mpesa._stk_request")
    def test_failed_callback_releases_sale_balance(self, stk_request):
        stk_request.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-request",
            "CheckoutRequestID": "ws_CO_failed",
        }
        push = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/callback/",
            callback_token="callback-failed",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        process_stk_callback(
            callback_token="callback-failed",
            payload={"Body": {"stkCallback": {
                "CheckoutRequestID": "ws_CO_failed",
                "ResultCode": 1032,
                "ResultDesc": "Request cancelled by user",
            }}},
        )
        push.refresh_from_db()
        push.payment_transaction.refresh_from_db()

        self.assertEqual(push.status, MpesaStkPush.Status.FAILED)
        self.assertEqual(push.payment_transaction.status, PaymentTransaction.Status.FAILED)
        self.assertEqual(self.sale.available_to_collect, Decimal("1500.00"))

    @patch("payments.mpesa._stk_request")
    def test_callback_can_arrive_before_initiation_response(self, stk_request):
        callback = {
            "Body": {"stkCallback": {
                "CheckoutRequestID": "ws_CO_fast_callback",
                "ResultCode": 0,
                "ResultDesc": "Success",
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": 1500},
                    {"Name": "MpesaReceiptNumber", "Value": "FAST1234567"},
                    {"Name": "PhoneNumber", "Value": 254712345678},
                ]},
            }}
        }

        def send_callback_before_response(*args, **kwargs):
            process_stk_callback(callback_token="callback-before-response", payload=callback)
            return {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-fast",
                "CheckoutRequestID": "ws_CO_fast_callback",
            }

        stk_request.side_effect = send_callback_before_response
        push = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/callback/",
            callback_token="callback-before-response",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        push.refresh_from_db()
        push.payment_transaction.refresh_from_db()
        self.assertEqual(push.checkout_request_id, "ws_CO_fast_callback")
        self.assertEqual(push.status, MpesaStkPush.Status.SUCCEEDED)
        self.assertEqual(push.payment_transaction.status, PaymentTransaction.Status.SUCCEEDED)

    @patch("payments.mpesa._stk_request")
    def test_callback_response_id_mismatch_downgrades_to_unknown(self, stk_request):
        callback = {
            "Body": {"stkCallback": {
                "CheckoutRequestID": "ws_CO_callback_id",
                "ResultCode": 0,
                "ResultDesc": "Success",
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": 1500},
                    {"Name": "MpesaReceiptNumber", "Value": "MISMATCH123"},
                    {"Name": "PhoneNumber", "Value": 254712345678},
                ]},
            }}
        }

        def send_mismatched_response(*args, **kwargs):
            process_stk_callback(callback_token="callback-id-mismatch", payload=callback)
            return {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-mismatch",
                "CheckoutRequestID": "ws_CO_different_id",
            }

        stk_request.side_effect = send_mismatched_response
        push = initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/callback/",
            callback_token="callback-id-mismatch",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        push.refresh_from_db()
        push.payment_transaction.refresh_from_db()
        self.assertEqual(push.status, MpesaStkPush.Status.UNKNOWN)
        self.assertEqual(push.payment_transaction.status, PaymentTransaction.Status.UNVERIFIED)

    def test_receipt_number_is_unique_case_insensitively(self):
        existing_payment = PaymentTransaction.objects.create(
            amount=Decimal("1500.00"), method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED, reference="STK-RECEIPT-1",
            recorded_by=self.owner,
        )
        MpesaStkPush.objects.create(
            payment_transaction=existing_payment,
            callback_token="receipt-already-used",
            phone_number="254712345678",
            mpesa_receipt_number="DUPLICATE123",
        )
        second_payment = PaymentTransaction.objects.create(
            amount=Decimal("1500.00"), method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED, reference="STK-RECEIPT-2",
            recorded_by=self.owner,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MpesaStkPush.objects.create(
                    payment_transaction=second_payment,
                    callback_token="receipt-reuse-test",
                    phone_number="254712345678",
                    mpesa_receipt_number="duplicate123",
                )

    def test_callback_with_wrong_checkout_id_is_rejected(self):
        payment = PaymentTransaction.objects.create(
            amount=Decimal("1500.00"),
            method=PaymentTransaction.Method.MPESA,
            status=PaymentTransaction.Status.UNVERIFIED,
            reference="STK-TESTCALLBACK",
            recorded_by=self.owner,
        )
        MpesaStkPush.objects.create(
            payment_transaction=payment,
            callback_token="wrong-checkout",
            checkout_request_id="expected-id",
            phone_number="254712345678",
        )
        with self.assertRaises(ValidationError):
            process_stk_callback(
                callback_token="wrong-checkout",
                payload={"Body": {"stkCallback": {
                    "CheckoutRequestID": "different-id",
                    "ResultCode": 0,
                }}},
            )

    @patch("payments.mpesa._stk_request")
    def test_success_callback_with_wrong_amount_is_rejected(self, stk_request):
        stk_request.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-request",
            "CheckoutRequestID": "ws_CO_wrong_amount",
        }
        initiate_stk_push(
            sale=self.sale,
            amount=Decimal("1500.00"),
            phone="0712345678",
            callback_url="https://lashpro-pos.fly.dev/callback/",
            callback_token="callback-wrong-amount",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        with self.assertRaises(ValidationError):
            process_stk_callback(
                callback_token="callback-wrong-amount",
                payload={"Body": {"stkCallback": {
                    "CheckoutRequestID": "ws_CO_wrong_amount",
                    "ResultCode": 0,
                    "CallbackMetadata": {"Item": [
                        {"Name": "Amount", "Value": 10},
                        {"Name": "MpesaReceiptNumber", "Value": "QWE1234567"},
                        {"Name": "PhoneNumber", "Value": 254712345678},
                    ]},
                }}},
            )
