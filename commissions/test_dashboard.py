from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Service
from commissions.services import complete_service_line
from sales.services import checkout_sale


User = get_user_model()


class TechnicianCommissionDashboardTests(TestCase):
    def test_manager_sees_commission_balance_for_named_technician(self):
        manager = User.objects.create_user(
            username="commission-manager",
            password="Test-Manager-Password!482",
            first_name="Mara",
            last_name="Manager",
            role=User.Role.MANAGER,
        )
        technician = User.objects.create_user(
            username="lash-tech-one",
            password="Test-Technician-Password!483",
            first_name="Amina",
            last_name="Technician",
            role=User.Role.TECHNICIAN,
        )
        service = Service.objects.create(
            name="Commission Test Classic Set",
            duration_minutes=90,
            price=Decimal("2500.00"),
            commission_eligible=True,
            commission_rate=Decimal("0.4000"),
        )
        sale = checkout_sale(
            cashier=manager,
            items=[{"service_id": service.pk, "technician_id": technician.pk}],
        )
        line = sale.lines.get(service=service)
        complete_service_line(sale_line=line, technician=technician, actor=manager)

        self.client.force_login(manager)
        response = self.client.get(reverse("commissions:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Commission balances by lash technician")
        self.assertContains(response, "Amina Technician")
        self.assertContains(response, "KSh 1000.00")
        self.assertContains(response, line.description)
