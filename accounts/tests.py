import os
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase

from accounts.models import User
from catalog.models import Product, Service
from customers.models import Customer
from inventory.models import InventoryMovement, ServiceConsumable


class SyntheticSeedCommandTests(TestCase):
    def test_seed_refuses_to_run_without_explicit_enablement(self):
        with patch.dict(os.environ, {"SYNTHETIC_DATA_ENABLED": "false"}):
            with self.assertRaisesMessage(CommandError, "Seeding is disabled"):
                call_command("seed_synthetic_data")

    def test_seed_is_repeatable_and_records_opening_stock_once(self):
        env = {
            "SYNTHETIC_DATA_ENABLED": "true",
            "DJANGO_ENV": "synthetic-test",
            "SYNTHETIC_DATA_CONFIRM_DATABASE": str(connection.settings_dict["NAME"]),
            "SYNTHETIC_STAFF_PASSWORD": "Synthetic-Alpha-Seed!5926-Only",
        }
        with patch.dict(os.environ, env):
            call_command("seed_synthetic_data", verbosity=0)
            first_snapshot = {
                "users": User.objects.filter(username__startswith="demo_").count(),
                "customers": Customer.objects.filter(name__startswith="Synthetic Test Customer").count(),
                "products": Product.objects.filter(sku__startswith="SYN-").count(),
                "services": Service.objects.filter(name__startswith="[Synthetic Test]").count(),
                "movements": InventoryMovement.objects.filter(reason__contains="lashpro-synthetic-alpha-v1").count(),
                "requirements": ServiceConsumable.objects.filter(
                    service__name="[Synthetic Test] Classic Lash Set"
                ).count(),
                "glue_stock": Product.objects.get(sku="SYN-LASH-GLUE-001").on_hand,
            }
            call_command("seed_synthetic_data", verbosity=0)
            second_snapshot = {
                "users": User.objects.filter(username__startswith="demo_").count(),
                "customers": Customer.objects.filter(name__startswith="Synthetic Test Customer").count(),
                "products": Product.objects.filter(sku__startswith="SYN-").count(),
                "services": Service.objects.filter(name__startswith="[Synthetic Test]").count(),
                "movements": InventoryMovement.objects.filter(reason__contains="lashpro-synthetic-alpha-v1").count(),
                "requirements": ServiceConsumable.objects.filter(
                    service__name="[Synthetic Test] Classic Lash Set"
                ).count(),
                "glue_stock": Product.objects.get(sku="SYN-LASH-GLUE-001").on_hand,
            }

        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(first_snapshot["users"], 4)
        self.assertEqual(first_snapshot["customers"], 5)
        self.assertEqual(first_snapshot["products"], 3)
        self.assertEqual(first_snapshot["services"], 3)
        self.assertEqual(first_snapshot["movements"], 3)
        self.assertEqual(first_snapshot["requirements"], 1)
