import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Service
from core.models import IntegrationSettings
from payments.models import MpesaC2BPayment, PaymentTransaction, SalePayment
from payments.services import allocate_c2b_mpesa_payment
from sales.models import Sale, SaleLine


class MpesaC2BCallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(
            username="c2b-cashier", password="test-password",
            role=User.Role.CASHIER, is_staff=True,
        )
        cls.service = Service.objects.create(
            name="C2B Test Service", duration_minutes=60, price=Decimal("800.00"),
        )
        cls.sale = Sale.objects.create(cashier=cls.cashier)
        SaleLine.from_service(sale=cls.sale, service=cls.service).save()
        cls.sale.status = Sale.Status.COMPLETED
        cls.sale.save(update_fields=("status",))

    def setUp(self):
        self.token = "c2b-test-callback-token"
        settings_record = IntegrationSettings.get_solo()
        settings_record.set_config({
            "mpesa_c2b_callback_token": self.token,
            "mpesa_c2b_shortcodes": "600001",
        })
        settings_record.save(update_fields=("encrypted_config", "updated_at"))
        self.payload = {
            "TransactionType": "Customer Merchant Payment",
            "TransID": "QWE123ASD9",
            "TransTime": "20261124191530",
            "TransAmount": "500.00",
            "BusinessShortCode": "600001",
            "BillRefNumber": "",
            "InvoiceNumber": "",
            "MSISDN": "2547 ***** 126",
            "FirstName": "JANE",
            "MiddleName": "",
            "LastName": "DOE",
        }

    def _post_callback(self, payload=None, token=None):
        return self.client.post(
            reverse("payments:c2b-confirmation", kwargs={"token": token or self.token}),
            data=json.dumps(payload if payload is not None else self.payload),
            content_type="application/json",
        )

    def test_callback_creates_confirmed_unallocated_payment_and_is_idempotent(self):
        first = self._post_callback()
        second = self._post_callback()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PaymentTransaction.objects.filter(reference="QWE123ASD9").count(), 1)
        payment = PaymentTransaction.objects.get(reference="QWE123ASD9")
        self.assertEqual(payment.status, PaymentTransaction.Status.SUCCEEDED)
        self.assertFalse(SalePayment.objects.filter(payment_transaction=payment).exists())
        callback = MpesaC2BPayment.objects.get(payment_transaction=payment)
        self.assertEqual(callback.payer_display_name, "JANE DOE")
        self.assertEqual(callback.masked_msisdn, "2547*****126")

    def test_callback_rejects_unconfigured_shortcode_and_wrong_token(self):
        payload = dict(self.payload, BusinessShortCode="600999")
        self.assertEqual(self._post_callback(payload).status_code, 400)
        self.assertEqual(self._post_callback(token="wrong-token").status_code, 400)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_cashier_allocates_confirmed_payment_after_customer_name_check(self):
        self.assertEqual(self._post_callback().status_code, 200)
        callback = MpesaC2BPayment.objects.get()
        allocation = allocate_c2b_mpesa_payment(
            c2b_payment=callback,
            sale=self.sale,
            actor=self.cashier,
            customer_confirmed=True,
        )
        self.assertEqual(allocation.amount, Decimal("500.00"))
        self.assertEqual(self.sale.pk, allocation.sale_id)
        self.assertEqual(self.sale.paid_amount, Decimal("500.00"))

    def test_allocation_requires_customer_confirmation(self):
        self.assertEqual(self._post_callback().status_code, 200)
        callback = MpesaC2BPayment.objects.get()
        with self.assertRaises(ValidationError):
            allocate_c2b_mpesa_payment(
                c2b_payment=callback, sale=self.sale, actor=self.cashier,
                customer_confirmed=False,
            )

    def test_one_c2b_receipt_cannot_be_allocated_twice(self):
        self.assertEqual(self._post_callback().status_code, 200)
        callback = MpesaC2BPayment.objects.get()
        allocate_c2b_mpesa_payment(
            c2b_payment=callback, sale=self.sale, actor=self.cashier,
            customer_confirmed=True,
        )
        with self.assertRaises(ValidationError):
            allocate_c2b_mpesa_payment(
                c2b_payment=callback, sale=self.sale, actor=self.cashier,
                customer_confirmed=True,
            )
