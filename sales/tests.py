from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import uuid

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.urls import reverse
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from customers.models import Customer
from payments.models import CashSession, PaymentTransaction, SalePayment
from .models import Sale, SaleLine
from .services import checkout_sale, record_sale_payment


class CheckoutFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(
            username="cashier",
            password="test-password",
            role=User.Role.CASHIER,
        )
        CashSession.objects.create(cashier=cls.cashier, opened_by=cls.cashier)
        cls.manager = User.objects.create_user(
            username="discount-manager",
            password="test-password",
            role=User.Role.MANAGER,
        )
        cls.customer = Customer.objects.create(
            name="Jane Customer",
            phone="0712345678",
        )
        cls.service = Service.objects.create(
            name="Classic Lash Set",
            duration_minutes=90,
            price=Decimal("2000.00"),
            commission_eligible=True,
        )
        cls.product = Product.objects.create(
            sku="GLUE-001",
            name="Lash Glue",
            cost_price=Decimal("200.00"),
            selling_price=Decimal("500.00"), on_hand=Decimal("10.000"),
        )

    def test_mixed_checkout_snapshots_lines_and_allocates_split_payments(self):
        sale = checkout_sale(
            cashier=self.cashier,
            customer=self.customer,
            items=[
                {"service_id": self.service.pk},
                {"product_id": self.product.pk},
            ],
            payments=[
                {"method": "CASH", "amount": "2000.00"},
                {"method": "MPESA", "amount": "500.00", "reference": "QAB123XYZ"},
            ],
        )

        self.assertEqual(sale.status, Sale.Status.COMPLETED)
        self.assertEqual(sale.total_amount, Decimal("2500.00"))
        self.assertEqual(sale.paid_amount, Decimal("2000.00"))
        self.assertEqual(sale.unverified_amount, Decimal("500.00"))
        self.assertEqual(sale.balance_due, Decimal("500.00"))
        self.assertEqual(sale.lines.count(), 2)
        self.assertEqual(sale.payment_allocations.count(), 2)

        service_line = sale.lines.get(service=self.service)
        product_line = sale.lines.get(product=self.product)
        self.assertEqual(service_line.description, "Classic Lash Set")
        self.assertEqual(service_line.unit_price, Decimal("2000.00"))
        self.assertEqual(product_line.description, "Lash Glue")
        self.assertEqual(product_line.unit_price, Decimal("500.00"))

        self.service.name = "Renamed Service"
        self.service.price = Decimal("2500.00")
        self.service.save()
        self.product.name = "Renamed Glue"
        self.product.selling_price = Decimal("600.00")
        self.product.save()
        sale.refresh_from_db()
        self.assertEqual(sale.total_amount, Decimal("2500.00"))
        self.assertEqual(service_line.description, "Classic Lash Set")
        self.assertEqual(product_line.unit_price, Decimal("500.00"))

        cash = PaymentTransaction.objects.get(sale_allocation__sale=sale, method="CASH")
        mpesa = PaymentTransaction.objects.get(sale_allocation__sale=sale, method="MPESA")
        self.assertEqual(cash.status, PaymentTransaction.Status.SUCCEEDED)
        self.assertEqual(mpesa.status, PaymentTransaction.Status.UNVERIFIED)
        self.assertEqual(mpesa.reference, "QAB123XYZ")
        self.assertEqual(SalePayment.objects.filter(sale=sale).count(), 2)

    def test_new_sale_line_requires_exactly_one_catalog_item(self):
        sale = Sale.objects.create(cashier=self.cashier)
        base = {
            "sale": sale,
            "description": "Invalid line",
            "quantity": 1,
            "unit_price": Decimal("100.00"),
        }

        with self.assertRaises(ValidationError):
            SaleLine(**base).full_clean()
        with self.assertRaises(ValidationError):
            SaleLine(**base, product=self.product, service=self.service).full_clean()

    def test_discount_reduces_line_total_and_cannot_exceed_subtotal(self):
        sale = checkout_sale(
            cashier=self.manager,
            items=[
                {
                    "product_id": self.product.pk,
                    "quantity": 2,
                    "discount": "100.00",
                    "discount_reason": "Alpha promotion approved by manager.",
                }
            ],
        )
        line = sale.lines.get()
        self.assertEqual(line.line_total(), Decimal("900.00"))
        self.assertEqual(sale.total_amount, Decimal("900.00"))
        event = AuditEvent.objects.get(object_type="sale_line_discount", object_id=str(line.pk))
        self.assertEqual(event.actor, self.manager)
        self.assertEqual(event.reason, "Alpha promotion approved by manager.")

        before = Sale.objects.count()
        with self.assertRaises(ValidationError):
            checkout_sale(
                cashier=self.cashier,
                items=[
                    {
                        "product_id": self.product.pk,
                        "quantity": 1,
                        "discount": "501.00",
                    }
                ],
            )
        self.assertEqual(Sale.objects.count(), before)

    def test_manual_mpesa_requires_reference_and_failed_checkout_rolls_back(self):
        before_sales = Sale.objects.count()
        before_payments = PaymentTransaction.objects.count()

        with self.assertRaises(ValidationError):
            checkout_sale(
                cashier=self.cashier,
                items=[{"service_id": self.service.pk}],
                payments=[{"method": "MPESA", "amount": "2000.00"}],
            )

        self.assertEqual(Sale.objects.count(), before_sales)
        self.assertEqual(PaymentTransaction.objects.count(), before_payments)

    def test_cash_overpayment_records_tender_and_change_separately(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
            payments=[{"method": "CASH", "amount": "2500.00"}],
        )
        payment = PaymentTransaction.objects.get(sale_allocation__sale=sale, method="CASH")
        allocation = SalePayment.objects.get(sale=sale, payment_transaction=payment)
        self.assertEqual(payment.amount, Decimal("2500.00"))
        self.assertEqual(allocation.amount, Decimal("2000.00"))
        self.assertEqual(allocation.change_due, Decimal("500.00"))
        self.assertEqual(sale.paid_amount, Decimal("2000.00"))
        self.assertEqual(sale.balance_due, Decimal("0.00"))

    def test_mixed_payment_allocates_mpesa_before_cash_and_calculates_change(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
            payments=[
                {"method": "CASH", "amount": "1500.00"},
                {"method": "MPESA", "amount": "1000.00", "reference": "MIXEDCHANGE001"},
            ],
        )
        cash = PaymentTransaction.objects.get(sale_allocation__sale=sale, method="CASH")
        cash_allocation = SalePayment.objects.get(sale=sale, payment_transaction=cash)
        self.assertEqual(cash.amount, Decimal("1500.00"))
        self.assertEqual(cash_allocation.amount, Decimal("1000.00"))
        self.assertEqual(cash_allocation.change_due, Decimal("500.00"))
        self.assertEqual(sale.unverified_amount, Decimal("1000.00"))
        self.assertEqual(sale.allocated_amount, Decimal("2000.00"))

    def test_receipt_pdf_returns_a_downloadable_pdf(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        response = self.client.get(
            reverse("sales:receipt_pdf", kwargs={"token": sale.receipt_token})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_later_cash_payment_reduces_balance(self):
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
        )
        payment = record_sale_payment(
            sale=sale,
            method=PaymentTransaction.Method.CASH,
            amount=Decimal("1000.00"),
        )

        sale.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.SUCCEEDED)
        self.assertEqual(sale.paid_amount, Decimal("1000.00"))
        self.assertEqual(sale.balance_due, Decimal("1000.00"))


    def test_cashier_cannot_apply_discount_even_with_a_reason(self):
        before = Sale.objects.count()
        with self.assertRaises(ValidationError):
            checkout_sale(
                cashier=self.cashier,
                items=[{
                    "product_id": self.product.pk,
                    "discount": "10.00",
                    "discount_reason": "Cashier attempted discount.",
                }],
            )
        self.assertEqual(Sale.objects.count(), before)
        self.assertFalse(AuditEvent.objects.filter(object_type="sale_line_discount").exists())

    def test_checkout_retry_uses_one_sale_and_deducts_stock_once(self):
        key = uuid.uuid4()
        starting_stock = self.product.on_hand
        first = checkout_sale(
            cashier=self.cashier,
            items=[{"product_id": self.product.pk}],
            idempotency_key=key,
        )
        retry = checkout_sale(
            cashier=self.cashier,
            items=[{"product_id": self.product.pk}],
            idempotency_key=key,
        )
        self.product.refresh_from_db()
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(self.product.on_hand, starting_stock - Decimal("1.000"))

    def test_payment_submission_is_idempotent_and_records_collector(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        key = uuid.uuid4()
        first = record_sale_payment(
            sale=sale, method="CASH", amount="1000.00",
            actor=self.cashier, idempotency_key=key,
        )
        retry = record_sale_payment(
            sale=sale, method="CASH", amount="1000.00",
            actor=self.cashier, idempotency_key=key,
        )
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(PaymentTransaction.objects.filter(sale_allocation__sale=sale).count(), 1)
        self.assertEqual(first.recorded_by, self.cashier)
        self.assertEqual(sale.available_to_collect, Decimal("1000.00"))

    def test_database_rejects_sale_line_without_catalog_item(self):
        sale = Sale.objects.create(cashier=self.cashier)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SaleLine.objects.create(
                    sale=sale, description="Unlinked", quantity=1,
                    unit_price=Decimal("100.00"),
                )

    def test_postgres_guards_prevent_financial_snapshot_edits(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL mutation guards are installed only on PostgreSQL.")
        sale = checkout_sale(
            cashier=self.cashier,
            items=[{"service_id": self.service.pk}],
            payments=[{"method": "CASH", "amount": "2000.00"}],
        )
        line = sale.lines.get()
        payment = PaymentTransaction.objects.get(sale_allocation__sale=sale)
        allocation = SalePayment.objects.get(sale=sale)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                SaleLine.objects.filter(pk=line.pk).update(unit_price=Decimal("1.00"))
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                PaymentTransaction.objects.filter(pk=payment.pk).update(reference="CHANGED")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                SalePayment.objects.filter(pk=allocation.pk).update(amount=Decimal("1.00"))


class ConcurrentStockCheckoutTests(TransactionTestCase):
    reset_sequences = True

    def test_only_one_concurrent_checkout_can_sell_the_last_unit(self):
        if connection.vendor != "postgresql":
            self.skipTest("This row-locking test requires PostgreSQL.")
        cashiers = [
            User.objects.create_user(username=f"stock-cashier-{index}", password="x", role=User.Role.CASHIER)
            for index in range(2)
        ]
        product = Product.objects.create(
            sku="LAST-UNIT", name="Last glue", cost_price=Decimal("10.00"),
            selling_price=Decimal("20.00"), on_hand=Decimal("1.000"),
        )
        barrier = Barrier(2)

        def attempt(cashier_id):
            close_old_connections()
            try:
                cashier = User.objects.get(pk=cashier_id)
                barrier.wait(timeout=15)
                try:
                    checkout_sale(cashier=cashier, items=[{"product_id": product.pk}])
                    return "sold"
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [cashier.pk for cashier in cashiers]))

        product.refresh_from_db()
        self.assertCountEqual(results, ["sold", "rejected"])
        self.assertEqual(product.on_hand, Decimal("0.000"))
        self.assertEqual(Sale.objects.filter(status=Sale.Status.COMPLETED).count(), 1)


    def test_technician_cannot_create_a_sale_through_the_service(self):
        technician = User.objects.create_user(
            username="checkout-technician", password="x", role=User.Role.TECHNICIAN,
        )
        service = Service.objects.create(
            name="Technician-only test", duration_minutes=45, price=Decimal("100.00"),
        )
        with self.assertRaises(ValidationError):
            checkout_sale(cashier=technician, items=[{"service_id": service.pk}])
