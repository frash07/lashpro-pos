import os
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.urls import reverse

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


class PeopleAccessAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username="people-access-owner",
            email="people-access-owner@example.test",
            password="test-password",
            role=User.Role.OWNER,
        )
        cls.manager = User.objects.create_user(
            username="people-access-manager",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="people-access-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )
        view_permissions = Permission.objects.filter(
            content_type__app_label__in=("accounts", "auth", "axes"),
            codename__in=(
                "view_user",
                "view_group",
                "view_accessattempt",
                "view_accessfailurelog",
                "view_accesslog",
            ),
        )
        cls.manager.user_permissions.add(*view_permissions)

    def test_user_admin_exposes_lashpro_role_on_add_and_change_forms(self):
        model_admin = admin.site._registry[User]
        self.assertIn("role", model_admin.list_display)
        self.assertIn("role", model_admin.list_filter)

        add_fields = {
            field
            for _title, options in model_admin.add_fieldsets
            for field in options["fields"]
        }
        change_fields = {
            field
            for _title, options in model_admin.fieldsets
            for field in options["fields"]
        }
        self.assertIn("role", add_fields)
        self.assertIn("role", change_fields)

        self.client.force_login(self.owner)
        add_response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertEqual(add_response.status_code, 200)
        self.assertContains(add_response, 'name="role"')

        staff_user = User.objects.create_user(
            username="people-access-role-edit",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        change_response = self.client.get(
            reverse("admin:accounts_user_change", args=[staff_user.pk])
        )
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'name="role"')

    def test_manager_can_review_people_and_security_records_with_explicit_view_permissions(self):
        self.client.force_login(self.manager)
        changelists = (
            "accounts_user_changelist",
            "auth_group_changelist",
            "axes_accessattempt_changelist",
            "axes_accessfailurelog_changelist",
            "axes_accesslog_changelist",
        )
        for url_name in changelists:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f"admin:{url_name}"))
                self.assertEqual(response.status_code, 200)

        # View permission allows review, but does not grant user/group write access.
        self.assertEqual(
            self.client.get(reverse("admin:accounts_user_add")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("admin:auth_group_add")).status_code,
            403,
        )

    def test_cashier_without_people_access_permissions_is_denied(self):
        self.client.force_login(self.cashier)
        changelists = (
            "accounts_user_changelist",
            "auth_group_changelist",
            "axes_accessattempt_changelist",
            "axes_accessfailurelog_changelist",
            "axes_accesslog_changelist",
        )
        for url_name in changelists:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f"admin:{url_name}"))
                self.assertEqual(response.status_code, 403)


class AuthAdminHubIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username="auth-hub-owner",
            email="auth-hub-owner@example.test",
            password="test-password",
            role=User.Role.OWNER,
        )

    def test_auth_app_index_renders_people_and_access_workspace(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("admin:app_list", kwargs={"app_label": "auth"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "People &amp; access")
        self.assertContains(response, "Open permission groups")
        self.assertContains(response, "Staff directory")
        self.assertContains(response, reverse("admin:auth_group_changelist"))
        self.assertContains(response, reverse("admin:auth_group_add"))
        self.assertContains(response, reverse("admin:accounts_user_changelist"))


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
