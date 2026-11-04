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

    def test_pos_catalog_includes_stock_and_stock_limited_cart_controls(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("sales:checkout"))
        product_item = next(
            item for item in response.context["catalog_items"]
            if item["id"] == f"product-{self.product.pk}"
        )

        self.assertEqual(product_item["stock"], float(self.product.on_hand))
        self.assertContains(response, "stock-badge")
        self.assertContains(response, "aria-disabled")
        self.assertContains(response, "maxSellableQuantity")
        self.assertContains(response, "sessionStorage.setItem")
        self.assertContains(response, "PENDING_CHECKOUT_STORAGE_KEY")

    def test_redesigned_checkout_uses_real_customer_and_manual_mpesa_fields(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("sales:checkout"))
        self.assertContains(response, 'name="customer"')
        self.assertContains(response, 'id="mpesa-reference"')
        self.assertContains(response, "recorded as unverified")
        self.assertNotContains(response, 'id="client-name"')
        self.assertNotContains(response, "processSTKPush")

    def test_technician_dropdown_uses_real_user_ids(self):
        other = User.objects.create_user(username="tech-two", password="pass", first_name="Faith", role=User.Role.TECHNICIAN)
        User.objects.create_user(username="tech-gone", password="pass", role=User.Role.TECHNICIAN, is_active=False)
        self.client.force_login(self.cashier)
        html = self.client.get(reverse("sales:checkout")).content.decode()
        select = html.split('id="staff-select"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'value="{self.tech.pk}"', select)
        self.assertIn(f'value="{other.pk}"', select)
        self.assertIn(">Faith<", select)
        self.assertNotIn("tech-gone", select)
        for hardcoded in ("Stacy (Senior Lash Artist)", "Faith (Lash Specialist)", "Lyn (Master Tech)"):
            self.assertNotIn(hardcoded, html)

    def test_each_service_line_keeps_its_own_technician(self):
        other = User.objects.create_user(username="tech-two", password="pass", role=User.Role.TECHNICIAN)
        self.client.force_login(self.cashier)
        data = self.data(amount="5000")
        data.update({"items-TOTAL_FORMS": "2", "items-1-product": "", "items-1-service": str(self.service.pk),
            "items-1-technician": str(other.pk), "items-1-quantity": "1", "items-1-discount": "0.00"})
        response = self.client.post(reverse("sales:checkout"), data)
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertEqual({line.technician_id for line in sale.lines.all()}, {self.tech.pk, other.pk})

    def test_technician_display_string_is_rejected(self):
        self.client.force_login(self.cashier)
        data = self.data()
        data["items-0-technician"] = "Stacy (Senior Lash Artist)"
        self.client.post(reverse("sales:checkout"), data)
        self.assertFalse(Sale.objects.exists())

    def test_product_line_with_technician_is_rejected(self):
        self.client.force_login(self.cashier)
        data = self.data(amount="800")
        data.update({"items-0-service": "", "items-0-product": str(self.product.pk), "items-0-technician": str(self.tech.pk)})
        self.client.post(reverse("sales:checkout"), data)
        self.assertFalse(Sale.objects.exists())

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

    def test_replayed_checkout_after_lost_response_does_not_double_charge_or_deduct_stock(self):
        self.client.force_login(self.cashier)
        data = self.data(method="CASH", amount="800.00")
        data.update({
            "items-0-product": str(self.product.pk),
            "items-0-service": "",
            "items-0-technician": "",
            "items-0-quantity": "1",
            "payments-0-amount": "800.00",
        })

        first_response = self.client.post(reverse("sales:checkout"), data)
        sale = Sale.objects.get()
        retry_response = self.client.post(reverse("sales:checkout"), data)

        receipt_url = reverse("sales:receipt", args=[sale.receipt_token])
        self.assertRedirects(first_response, receipt_url)
        self.assertRedirects(retry_response, receipt_url)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(sale.lines.count(), 1)
        self.assertEqual(
            PaymentTransaction.objects.filter(sale_allocation__sale=sale).count(),
            1,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.on_hand, Decimal("9.000"))

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
        self.assertTrue(response.context["checkout_status_known_failure"])
        self.assertContains(response, "CHECKOUT_STATUS_KNOWN_FAILURE = true")

    def test_client_cannot_override_catalog_price(self):
        self.client.force_login(self.cashier)
        data = self.data()
        data.update({"items-0-product":str(self.product.pk),"items-0-service":"",
                     "items-0-technician":"","items-0-unit_price":"1.00","payments-0-amount":"800"})
        self.client.post(reverse("sales:checkout"), data)
        self.assertEqual(Sale.objects.get().total_amount, Decimal("800.00"))


    def test_receipt_clears_only_the_matching_pending_checkout_key(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        response = self.client.get(reverse("sales:receipt", args=[sale.receipt_token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(sale.checkout_idempotency_key))
        self.assertContains(response, "pending.idempotencyKey === completedCheckoutKey")
        self.assertContains(response, 'window.sessionStorage.removeItem(storageKey)')

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


class VatInclusiveTotalsTests(TestCase):
    """Catalog prices are VAT-inclusive: VAT is extracted from the total, never added on top."""

    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="vat-cashier", password="pass", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="vat-manager", password="pass", role=User.Role.MANAGER)
        cls.tech = User.objects.create_user(username="vat-tech", password="pass", role=User.Role.TECHNICIAN)
        for user in (cls.cashier, cls.manager):
            CashSession.objects.create(cashier=user, opened_by=user)
        cls.service = Service.objects.create(name="Gross Priced Set", duration_minutes=90, price=Decimal("11600.00"))

    def test_vat_is_extracted_from_the_gross_total(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk, "technician_id": self.tech.pk}],
            payments=[{"method": "CASH", "amount": "11600.00"}],
        )
        self.assertEqual(sale.total_amount, Decimal("11600.00"))
        self.assertEqual(sale.vat_amount, Decimal("1600.00"))
        self.assertEqual(sale.net_amount, Decimal("10000.00"))
        self.assertEqual(sale.balance_due, Decimal("0.00"))

    def test_vat_rounds_to_cents_and_net_plus_vat_equals_total(self):
        service = Service.objects.create(name="Odd Priced Set", duration_minutes=30, price=Decimal("100.00"))
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": service.pk, "technician_id": self.tech.pk}],
            payments=[{"method": "CASH", "amount": "100.00"}],
        )
        self.assertEqual(sale.vat_amount, Decimal("13.79"))
        self.assertEqual(sale.net_amount, Decimal("86.21"))
        self.assertEqual(sale.net_amount + sale.vat_amount, sale.total_amount)

    def test_discounted_checkout_payment_matches_backend_total(self):
        # What checkout.html posts for a 10% promo: a per-line discount and a payment equal to
        # the discounted VAT-inclusive total, with no VAT added on top.
        self.client.force_login(self.manager)
        response = self.client.post(reverse("sales:checkout"), {
            "idempotency_key": "22222222-2222-4222-8222-222222222222",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "20",
            "items-0-product": "", "items-0-service": str(self.service.pk), "items-0-technician": str(self.tech.pk),
            "items-0-quantity": "1", "items-0-discount": "1160.00", "items-0-discount_reason": "Promo code STUDENT10",
            "payments-TOTAL_FORMS": "1", "payments-INITIAL_FORMS": "0", "payments-MIN_NUM_FORMS": "0", "payments-MAX_NUM_FORMS": "10",
            "payments-0-method": "CASH", "payments-0-amount": "10440.00", "payments-0-reference": "",
        })
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertEqual(sale.total_amount, Decimal("10440.00"))
        self.assertEqual(sale.paid_amount, Decimal("10440.00"))
        self.assertEqual(sale.balance_due, Decimal("0.00"))
        self.assertEqual(sale.vat_amount, Decimal("1440.00"))
        self.assertEqual(sale.net_amount, Decimal("9000.00"))

    def test_receipt_and_pdf_show_net_and_included_vat(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk, "technician_id": self.tech.pk}],
            payments=[{"method": "CASH", "amount": "11600.00"}],
        )
        response = self.client.get(reverse("sales:receipt", args=[sale.receipt_token]))
        self.assertContains(response, "VAT included (16%)")
        self.assertContains(response, "KSh 1,600.00")
        self.assertContains(response, "KSh 10,000.00")
        self.assertEqual(self.client.get(reverse("sales:receipt_pdf", args=[sale.receipt_token])).status_code, 200)
