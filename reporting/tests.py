from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from catalog.models import Service
from payments.models import CashSession, PaymentTransaction
from payments.services import reconcile_manual_mpesa
from sales.services import checkout_sale


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

    def test_cashier_cannot_view_reports(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("reporting:dashboard")).status_code, 403)
