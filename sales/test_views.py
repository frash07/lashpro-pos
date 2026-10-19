from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from catalog.models import Product, Service
from customers.models import Customer
from payments.models import CashSession, PaymentTransaction
from sales.services import checkout_sale, issue_refund, request_sale_refund
from .models import Sale


class CashierViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="cashier-ui", password="pass", role=User.Role.CASHIER)
        CashSession.objects.create(cashier=cls.cashier, opened_by=cls.cashier)
        cls.tech = User.objects.create_user(username="tech-ui", password="pass", role=User.Role.TECHNICIAN)
        cls.customer = Customer.objects.create(name="Amina")
        cls.service = Service.objects.create(name="Classic Set", duration_minutes=75, price=Decimal("2500"))
        cls.product = Product.objects.create(sku="UI-GLUE", name="Lash Glue",
            cost_price=Decimal("300"), selling_price=Decimal("800"), on_hand=Decimal("10.000"))

    def data(self, method="CASH", amount="2500", reference=""):
        return {"customer": str(self.customer.pk),
            "idempotency_key": "11111111-1111-4111-8111-111111111111",
            "items-TOTAL_FORMS":"1","items-INITIAL_FORMS":"0","items-MIN_NUM_FORMS":"0","items-MAX_NUM_FORMS":"20",
            "items-0-product":"","items-0-service":str(self.service.pk),"items-0-technician":str(self.tech.pk),"items-0-quantity":"1","items-0-discount":"0.00",
            "payments-TOTAL_FORMS":"1","payments-INITIAL_FORMS":"0","payments-MIN_NUM_FORMS":"0","payments-MAX_NUM_FORMS":"10",
            "payments-0-method":method,"payments-0-amount":amount,"payments-0-reference":reference}

    def test_checkout_requires_login_and_shows_catalog(self):
        self.assertEqual(self.client.get(reverse("sales:checkout")).status_code, 302)
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("sales:checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classic Set")
        self.assertContains(response, "Lash Glue")

    def test_discount_controls_are_shown_only_to_managers(self):
        self.client.force_login(self.cashier)
        cashier_response = self.client.get(reverse("sales:checkout"))
        self.assertNotContains(cashier_response, "Discount (KSh)")
        self.assertContains(cashier_response, "Discounts require a manager.")

        manager = User.objects.create_user(
            username="checkout-manager", password="pass", role=User.Role.MANAGER
        )
        self.client.force_login(manager)
        manager_response = self.client.get(reverse("sales:checkout"))
        self.assertContains(manager_response, "Discount (KSh)")

    def test_checkout_uses_cash_and_mpesa_specific_amount_labels(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("sales:checkout"))
        self.assertContains(response, "Payment amount (KSh)")
        self.assertContains(response, "Cash received (KSh)")
        self.assertContains(response, "Amount applied (KSh)")
        self.assertContains(response, "M-Pesa awaiting verification")

    def test_technician_is_denied(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("sales:checkout")).status_code, 403)

    def test_cash_checkout_and_receipt(self):
        self.client.force_login(self.cashier)
        response = self.client.post(reverse("sales:checkout"), self.data())
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertEqual(sale.customer, self.customer)
        self.assertEqual(sale.paid_amount, Decimal("2500.00"))
        self.assertContains(self.client.get(reverse("sales:receipt", args=[sale.receipt_token])), "Sale receipt")

    def test_mpesa_reference_is_saved_unverified(self):
        self.client.force_login(self.cashier)
        self.client.post(reverse("sales:checkout"), self.data("MPESA", reference="QAB123XYZ"))
        sale = Sale.objects.get()
        payment = PaymentTransaction.objects.get(sale_allocation__sale=sale)
        self.assertEqual(payment.status, PaymentTransaction.Status.UNVERIFIED)
        self.assertEqual(payment.reference, "QAB123XYZ")

    def test_empty_cart_does_not_create_sale(self):
        self.client.force_login(self.cashier)
        data = self.data()
        data["items-0-service"] = ""
        response = self.client.post(reverse("sales:checkout"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), 0)

    def test_client_cannot_override_catalog_price(self):
        self.client.force_login(self.cashier)
        data = self.data()
        data.update({"items-0-product":str(self.product.pk),"items-0-service":"",
                     "items-0-technician":"","items-0-unit_price":"1.00","payments-0-amount":"800"})
        self.client.post(reverse("sales:checkout"), data)
        self.assertEqual(Sale.objects.get().total_amount, Decimal("800.00"))


    def test_receipt_uses_public_random_token_without_database_id(self):
        from sales.services import checkout_sale
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        response = self.client.get(reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(sale.receipt_token), 40)
        self.assertContains(response, sale.receipt_number)
        self.assertNotContains(response, f"Sale #{sale.pk}")


    def test_receipt_masks_mpesa_reference_and_sets_privacy_headers(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
            payments=[{"method": "MPESA", "amount": "2500.00", "reference": "QAB123XYZ"}],
        )
        response = self.client.get(reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertContains(response, "••••3XYZ")
        self.assertNotContains(response, "QAB123XYZ")

    def test_balance_payment_screen_records_cash_idempotently(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        self.client.force_login(self.cashier)
        self.assertContains(self.client.get(reverse("sales:payments")), sale.receipt_number)
        data = {
            "sale": str(sale.pk),
            "idempotency_key": "22222222-2222-4222-8222-222222222222",
            "method": "CASH",
            "amount": "1000.00",
            "reference": "",
        }
        self.assertEqual(self.client.post(reverse("sales:payments"), data).status_code, 302)
        self.assertEqual(self.client.post(reverse("sales:payments"), data).status_code, 302)
        self.assertEqual(PaymentTransaction.objects.filter(sale_allocation__sale=sale).count(), 1)
        payment = PaymentTransaction.objects.get(sale_allocation__sale=sale)
        self.assertEqual(payment.recorded_by, self.cashier)
        self.assertEqual(payment.cash_session.cashier, self.cashier)

    def test_cashier_cannot_collect_payment_for_another_cashiers_sale(self):
        other = User.objects.create_user(username="other-cashier", password="pass", role=User.Role.CASHIER)
        sale = checkout_sale(cashier=other, items=[{"service_id": self.service.pk}])
        self.client.force_login(self.cashier)
        response = self.client.post(reverse("sales:payments"), {
            "sale": str(sale.pk),
            "idempotency_key": "33333333-3333-4333-8333-333333333333",
            "method": "CASH",
            "amount": "1000.00",
            "reference": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaymentTransaction.objects.filter(sale_allocation__sale=sale).count(), 0)


    def test_receipt_shows_net_total_after_issued_refund(self):
        manager = User.objects.create_user(username="receipt-manager", password="pass", role=User.Role.MANAGER)
        CashSession.objects.create(cashier=manager, opened_by=manager)
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
            payments=[{"method": "CASH", "amount": "2500.00"}],
        )
        refund = request_sale_refund(
            sale=sale,
            items=[{"sale_line_id": sale.lines.get().pk, "quantity": 1}],
            method="CASH",
            reason="Customer requested a full refund.",
            requested_by=self.cashier,
        )
        issue_refund(refund=refund, approver=manager, review_reason="Approved and paid.")
        response = self.client.get(reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertContains(response, "Refunds issued: KSh 2500.00")
        self.assertContains(response, "Net sale total: KSh 0.00")
        self.assertContains(response, "Refund issued")
