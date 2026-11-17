import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Product, Service
from payments.models import CashSession, PaymentTransaction
from payments.services import reconcile_manual_mpesa
from sales.services import checkout_sale
from storefront.models import StorefrontOrder
from storefront.services import create_storefront_order, transition_storefront_order


class DailyReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="report-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="report-manager", password="x", role=User.Role.MANAGER)
        cls.service = Service.objects.create(name="Lash set", duration_minutes=60, price=Decimal("1000.00"))
        CashSession.objects.create(cashier=cls.cashier, opened_by=cls.cashier)

    def test_report_separates_unverified_mpesa_until_reconciled(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}], payments=[
            {"method": "CASH", "amount": "500.00"},
            {"method": "MPESA", "amount": "500.00", "reference": "REPORT123"},
        ])
        self.client.force_login(self.manager)
        response = self.client.get(reverse("reporting:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["confirmed_collection"], Decimal("500.00"))
        self.assertEqual(response.context["report"]["unverified_collection"], Decimal("500.00"))
        payment = PaymentTransaction.objects.get(sale_allocation__sale=sale, method="MPESA")
        reconcile_manual_mpesa(payment=payment, actor=self.manager, decision="CONFIRMED", reason="Matched to statement.")
        response = self.client.get(reverse("reporting:dashboard"))
        self.assertEqual(response.context["report"]["confirmed_collection"], Decimal("1000.00"))
        self.assertEqual(response.context["report"]["unverified_collection"], Decimal("0.00"))

    def test_fulfilled_online_order_appears_as_revenue_without_fabricated_collection(self):
        product = Product.objects.create(
            sku="REPORT-ONLINE-001",
            name="Online report product",
            cost_price=Decimal("250.00"),
            selling_price=Decimal("750.00"),
            on_hand=Decimal("4.000"),
            active=True,
        )
        order = create_storefront_order(
            items={str(product.pk): 2},
            customer_name="Online Report Guest",
            customer_email="online-report@example.test",
            customer_phone="+254700111222",
            idempotency_key=uuid.uuid4(),
        )
        for target_status in (
            StorefrontOrder.Status.CONFIRMED,
            StorefrontOrder.Status.READY,
            StorefrontOrder.Status.FULFILLED,
        ):
            transition_storefront_order(
                order=order,
                target_status=target_status,
                actor=self.cashier,
            )

        order.refresh_from_db()
        self.assertIsNotNone(order.sale)
        self.assertEqual(order.sale.total_amount, Decimal("1500.00"))
        self.assertEqual(order.sale.paid_amount, Decimal("0.00"))

        self.client.force_login(self.manager)
        today = timezone.localdate()
        response = self.client.get(reverse("reporting:dashboard"), {
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["completed_sale_count"], 1)
        self.assertEqual(response.context["report"]["gross_sales"], Decimal("1500.00"))
        self.assertEqual(response.context["report"]["confirmed_collection"], Decimal("0.00"))
        self.assertEqual(response.context["report"]["unverified_collection"], Decimal("0.00"))

    def test_cashier_cannot_view_reports(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("reporting:dashboard")).status_code, 403)
