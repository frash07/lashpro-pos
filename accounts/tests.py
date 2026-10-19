import os
from unittest.mock import patch

from django.contrib import admin
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase

from accounts.management.commands.seed_synthetic_data import SYNTHETIC_SALE_KEY
from accounts.models import User
from catalog.models import Product, Service
from commissions.models import CommissionLedgerEntry
from customers.models import Customer
from inventory.models import InventoryMovement, ServiceConsumable
from payments.models import CashSession, PaymentTransaction
from sales.models import Sale


class UserAdminTests(TestCase):
    def test_custom_user_model_is_registered_for_staff_provisioning(self):
        self.assertTrue(admin.site.is_registered(User))


class SyntheticSeedCommandTests(TestCase):
    def test_seed_refuses_to_run_without_explicit_enablement(self):
        with patch.dict(os.environ, {"SYNTHETIC_DATA_ENABLED": "false"}):
            with self.assertRaisesMessage(CommandError, "Seeding is disabled"):
                call_command("seed_synthetic_data")

    def test_seed_is_repeatable_and_records_a_sample_sale_once(self):
        env = {
            "SYNTHETIC_DATA_ENABLED": "true",
            "DJANGO_ENV": "synthetic-test",
            "SYNTHETIC_DATA_CONFIRM_DATABASE": str(connection.settings_dict["NAME"]),
            "SYNTHETIC_STAFF_PASSWORD": "Synthetic-Alpha-Seed!5926-Only",
        }
        with patch.dict(os.environ, env):
            call_command("seed_synthetic_data", verbosity=0)
            first_snapshot = self._snapshot()
            call_command("seed_synthetic_data", verbosity=0)
            second_snapshot = self._snapshot()

        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(first_snapshot["users"], 4)
        self.assertEqual(first_snapshot["customers"], 5)
        self.assertEqual(first_snapshot["products"], 3)
        self.assertEqual(first_snapshot["services"], 3)
        self.assertEqual(first_snapshot["opening_receipts"], 3)
        self.assertEqual(first_snapshot["consumable_rules"], 1)
        self.assertEqual(first_snapshot["sales"], 1)
        self.assertEqual(first_snapshot["payments"], 2)
        self.assertEqual(first_snapshot["earned_commissions"], 1)
        self.assertEqual(first_snapshot["cash_sessions"], 1)

        sale = Sale.objects.get(checkout_idempotency_key=SYNTHETIC_SALE_KEY)
        self.assertEqual(sale.total_amount, sale.paid_amount + sale.unverified_amount)
        self.assertEqual(sale.unverified_amount, sale.payment_allocations.filter(
            payment_transaction__method=PaymentTransaction.Method.MPESA
        ).get().amount)

    def _snapshot(self):
        sale_filter = {"checkout_idempotency_key": SYNTHETIC_SALE_KEY}
        return {
            "users": User.objects.filter(username__startswith="demo_").count(),
            "customers": Customer.objects.filter(name__startswith="Synthetic Test Customer").count(),
            "products": Product.objects.filter(sku__startswith="SYN-").count(),
            "services": Service.objects.filter(name__startswith="[Synthetic Test]").count(),
            "opening_receipts": InventoryMovement.objects.filter(
                reason__contains="lashpro-synthetic-alpha-v1",
                movement_type=InventoryMovement.Type.PURCHASE,
            ).count(),
            "consumable_rules": ServiceConsumable.objects.filter(
                service__name="[Synthetic Test] Classic Lash Set"
            ).count(),
            "sales": Sale.objects.filter(**sale_filter).count(),
            "payments": PaymentTransaction.objects.filter(
                sale_allocation__sale__checkout_idempotency_key=SYNTHETIC_SALE_KEY
            ).count(),
            "earned_commissions": CommissionLedgerEntry.objects.filter(
                sale_line__sale__checkout_idempotency_key=SYNTHETIC_SALE_KEY,
                entry_type=CommissionLedgerEntry.Type.EARNED,
            ).count(),
            "cash_sessions": CashSession.objects.filter(cashier__username="demo_cashier").count(),
            "glue_stock": Product.objects.get(sku="SYN-LASH-GLUE-001").on_hand,
            "cleanser_stock": Product.objects.get(sku="SYN-LASH-SHAMPOO-001").on_hand,
        }
