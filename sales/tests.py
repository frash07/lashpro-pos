from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import uuid

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.urls import reverse
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from customers.models import Customer
from payments.models import CashSession, PaymentTransaction, SalePayment
from commissions.models import CommissionLedgerEntry
from .models import Sale, SaleLine, SaleRefund
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


class AdminSuiteGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="gate-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="gate-manager", password="x", role=User.Role.MANAGER, is_staff=True)

    def _create_unverified_mpesa(self, count):
        for index in range(count):
            PaymentTransaction.objects.create(
                method=PaymentTransaction.Method.MPESA,
                status=PaymentTransaction.Status.UNVERIFIED,
                amount=Decimal("100.00"),
                reference=f"GATE{index:06d}",
            )

    def test_cashier_does_not_see_admin_suite_switch(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("sales:checkout"))
        self.assertFalse(response.context["admin_suite"]["is_manager"])
        self.assertNotContains(response, 'id="nav-admin-btn"')

    def test_manager_sees_admin_suite_switch_and_deep_links(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("sales:checkout"))
        self.assertTrue(response.context["admin_suite"]["is_manager"])
        self.assertContains(response, 'id="nav-admin-btn"')
        self.assertContains(response, 'href="/admin-suite/"')
        for name in ("sales:refunds", "payments:cash-session", "sales:services", "inventory:receive", "reporting:dashboard"):
            self.assertContains(response, reverse(name))

    def test_pending_count_includes_all_unverified_mpesa_not_just_recent_rows(self):
        self._create_unverified_mpesa(20)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("sales:checkout"))
        self.assertEqual(response.context["admin_suite"]["pending_reconciliation_count"], 20)


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



class SalesAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(
            username="sales-admin-manager",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="sales-admin-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )
        cls.technician = User.objects.create_user(
            username="sales-admin-technician",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        cls.service = Service.objects.create(
            name="Admin Test Lash Set",
            duration_minutes=60,
            price=Decimal("1500.00"),
            commission_eligible=True,
            commission_rate=Decimal("0.4000"),
        )
        cls.product = Product.objects.create(
            sku="ADMIN-SALES-001",
            name="Admin Test Adhesive",
            cost_price=Decimal("100.00"),
            selling_price=Decimal("250.00"),
            on_hand=Decimal("5.000"),
        )
        manager_permissions = Permission.objects.filter(
            codename__in=(
                "view_sale", "change_sale",
                "view_saleline", "change_saleline",
                "view_salerefund",
            )
        )
        cls.manager.user_permissions.add(*manager_permissions)
        cashier_line_permission = Permission.objects.get(codename="change_saleline")
        cls.cashier.user_permissions.add(cashier_line_permission)

    def _create_sale(self, *, include_product=False):
        items = [{"service_id": self.service.pk}]
        if include_product:
            items.append({"product_id": self.product.pk})
        return checkout_sale(cashier=self.cashier, items=items)

    def test_sale_admin_is_read_only_and_disallows_add_and_delete(self):
        sale = self._create_sale()
        self.client.force_login(self.manager)

        response = self.client.get(reverse("admin:sales_sale_changelist"))
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(reverse("admin:sales_sale_change", args=[sale.pk]))
        self.assertEqual(detail.status_code, 200)

        sale_admin = admin.site._registry[Sale]
        self.assertEqual(
            set(sale_admin.readonly_fields),
            {field.name for field in Sale._meta.fields},
        )
        self.assertFalse(sale_admin.has_add_permission(detail.wsgi_request))
        self.assertFalse(sale_admin.has_delete_permission(detail.wsgi_request, sale))
        self.assertEqual(
            self.client.get(reverse("admin:sales_sale_add")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("admin:sales_sale_delete", args=[sale.pk])).status_code,
            403,
        )

    def test_sale_line_admin_lists_service_lines_and_limits_changes_to_managers(self):
        sale = self._create_sale(include_product=True)
        service_line = sale.lines.get(service=self.service)
        product_line = sale.lines.get(product=self.product)
        self.client.force_login(self.manager)

        response = self.client.get(reverse("admin:sales_saleline_changelist"))
        self.assertEqual(response.status_code, 200)
        listed_ids = {line.pk for line in response.context["cl"].result_list}
        self.assertIn(service_line.pk, listed_ids)
        self.assertNotIn(product_line.pk, listed_ids)

        line_admin = admin.site._registry[SaleLine]
        self.assertTrue(line_admin.has_change_permission(response.wsgi_request, service_line))

        self.client.force_login(self.cashier)
        cashier_response = self.client.get(
            reverse("admin:sales_saleline_change", args=[service_line.pk])
        )
        self.assertEqual(cashier_response.status_code, 200)
        self.assertFalse(
            line_admin.has_change_permission(cashier_response.wsgi_request, service_line)
        )

    def test_manager_admin_action_completes_service_and_accrues_commission(self):
        sale = self._create_sale()
        line = sale.lines.get(service=self.service)
        line.technician = self.technician
        line.save(update_fields=("technician",))
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("admin:sales_saleline_changelist"),
            {
                "action": "complete_services",
                "_selected_action": [str(line.pk)],
                "index": "0",
            },
        )
        self.assertEqual(response.status_code, 302)

        line.refresh_from_db()
        self.assertIsNotNone(line.service_completed_at)
        self.assertEqual(line.completed_by, self.manager)
        self.assertTrue(
            CommissionLedgerEntry.objects.filter(
                sale_line=line,
                entry_type=CommissionLedgerEntry.Type.EARNED,
                technician=self.technician,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                object_type="sale_line",
                object_id=str(line.pk),
            ).exists()
        )

    def test_refund_admin_is_read_only_and_preserves_refund_records(self):
        sale = self._create_sale()
        refund = SaleRefund.objects.create(
            sale=sale,
            amount=Decimal("100.00"),
            method=SaleRefund.Method.CASH,
            reason="Admin integration test refund request.",
            requested_by=self.cashier,
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("admin:sales_salerefund_changelist"))
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(
            reverse("admin:sales_salerefund_change", args=[refund.pk])
        )
        self.assertEqual(detail.status_code, 200)

        refund_admin = admin.site._registry[SaleRefund]
        self.assertEqual(
            set(refund_admin.readonly_fields),
            {field.name for field in SaleRefund._meta.fields},
        )
        self.assertFalse(refund_admin.has_add_permission(detail.wsgi_request))
        self.assertFalse(refund_admin.has_delete_permission(detail.wsgi_request, refund))
        self.assertEqual(
            self.client.get(reverse("admin:sales_salerefund_add")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("admin:sales_salerefund_delete", args=[refund.pk])
            ).status_code,
            403,
        )
