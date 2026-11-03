from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Product, Service
from commissions.models import CommissionLedgerEntry, CommissionPayoutRecord, CommissionPayoutRequest
from commissions.services import approve_commission_payout, complete_service_line, request_commission_payout
from inventory.models import InventoryMovement, ServiceConsumable
from payments.services import reconcile_mpesa_payout
from sales.services import checkout_sale


class CommissionEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = User.objects.create_user(username="commission-cashier", password="x", role=User.Role.CASHIER)
        cls.manager = User.objects.create_user(username="commission-manager", password="x", role=User.Role.MANAGER)
        cls.technician = User.objects.create_user(username="commission-tech", password="x", role=User.Role.TECHNICIAN)
        cls.glue = Product.objects.create(sku="CONS-1", name="Glue", cost_price=Decimal("100"), selling_price=Decimal("500"), on_hand=Decimal("5.000"))
        cls.service = Service.objects.create(name="Lash set", duration_minutes=60, price=Decimal("1000.00"), commission_eligible=True)
        ServiceConsumable.objects.create(service=cls.service, product=cls.glue, quantity_per_service=Decimal("0.500"))

    def test_service_completion_consumes_recipe_and_earns_commission(self):
        sale = checkout_sale(cashier=self.manager, items=[{"service_id": self.service.pk, "discount": "100.00", "discount_reason": "Manager-approved lash promotion."}])
        line = sale.lines.get()
        entry = complete_service_line(sale_line=line, technician=self.technician, actor=self.manager)
        self.glue.refresh_from_db()
        self.assertEqual(self.glue.on_hand, Decimal("4.500"))
        self.assertEqual(entry.base_amount, Decimal("900.00"))
        self.assertEqual(entry.amount, Decimal("360.00"))
        self.assertEqual(entry.rate_snapshot, Decimal("0.4000"))
        self.assertTrue(AuditEvent.objects.filter(
            event_type=AuditEvent.EventType.SERVICE_COMPLETION,
            object_type="sale_line", object_id=str(line.pk),
        ).exists())
        self.assertEqual(InventoryMovement.objects.filter(sale_line=line, movement_type=InventoryMovement.Type.SERVICE_USE).count(), 1)

    def test_mpesa_commission_payout_stays_unverified_until_reconciled(self):
        sale = checkout_sale(cashier=self.cashier, items=[{"service_id": self.service.pk}])
        line = sale.lines.get()
        complete_service_line(sale_line=line, technician=self.technician, actor=self.manager)
        request = request_commission_payout(technician=self.technician, amount="100.00", method="MPESA", reference="PAYOUT123", reason="Daily payout.", requested_by=self.technician)
        record = approve_commission_payout(payout=request, approver=self.manager)
        request.refresh_from_db()
        self.assertEqual(request.status, CommissionPayoutRequest.Status.ISSUED)
        self.assertEqual(record.verification_status, "UNVERIFIED")
        reconcile_mpesa_payout(payout_type="COMMISSION", payout=record, actor=self.manager, decision="CONFIRMED", reason="Matched to outgoing statement.")
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "CONFIRMED")
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEvent.EventType.PAYMENT_RECONCILIATION, object_type="commission_payout").exists())
        with self.assertRaises(TypeError):
            CommissionPayoutRecord.objects.filter(pk=record.pk).update(amount=Decimal("1.00"))


class ArtistCommissionsAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username="commission-admin-owner", email="commission-admin@example.test",
            password="test-password", role=User.Role.OWNER,
        )
        cls.manager = User.objects.create_user(
            username="commission-admin-manager", password="test-password",
            role=User.Role.MANAGER, is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="commission-admin-cashier", password="test-password",
            role=User.Role.CASHIER, is_staff=True,
        )
        cls.technician = User.objects.create_user(
            username="commission-admin-tech", password="test-password",
            role=User.Role.TECHNICIAN,
        )
        service = Service.objects.create(
            name="Commission Admin Service", duration_minutes=60,
            price=Decimal("1000.00"), commission_eligible=True,
        )
        sale = checkout_sale(cashier=cls.manager, items=[{"service_id": service.pk}])
        line = sale.lines.get()
        cls.ledger_entry = complete_service_line(
            sale_line=line, technician=cls.technician, actor=cls.manager,
        )
        cls.payout_request = request_commission_payout(
            technician=cls.technician, amount="100.00", method="MPESA",
            reference="ADMIN-COMMISSION-001", reason="Admin test payout.",
            requested_by=cls.technician,
        )
        cls.payout_record = approve_commission_payout(
            payout=cls.payout_request, approver=cls.manager,
        )
        cls.manager.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="commissions",
            codename__in=(
                "view_commissionledgerentry",
                "view_commissionpayoutrecord",
                "view_commissionpayoutrequest",
            ),
        ))

    def test_commission_admin_records_are_read_only_and_cannot_be_added_or_deleted(self):
        records = (
            (CommissionLedgerEntry, self.ledger_entry, "commissions_commissionledgerentry"),
            (CommissionPayoutRecord, self.payout_record, "commissions_commissionpayoutrecord"),
            (CommissionPayoutRequest, self.payout_request, "commissions_commissionpayoutrequest"),
        )
        self.client.force_login(self.owner)
        for model, obj, admin_name in records:
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                change_url = reverse(f"admin:{admin_name}_change", args=[obj.pk])
                response = self.client.get(change_url)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(model_admin.has_add_permission(response.wsgi_request))
                self.assertFalse(model_admin.has_delete_permission(response.wsgi_request, obj))
                self.assertTrue(
                    {field.name for field in model._meta.fields}.issubset(
                        set(model_admin.get_readonly_fields(response.wsgi_request, obj))
                    )
                )
                self.assertEqual(self.client.get(reverse(f"admin:{admin_name}_add")).status_code, 403)
                self.assertEqual(
                    self.client.get(reverse(f"admin:{admin_name}_delete", args=[obj.pk])).status_code,
                    403,
                )

    def test_manager_can_review_commission_records_but_cashier_cannot(self):
        self.client.force_login(self.manager)
        for url_name in (
            "commissions_commissionledgerentry_changelist",
            "commissions_commissionpayoutrecord_changelist",
            "commissions_commissionpayoutrequest_changelist",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(f"admin:{url_name}")).status_code, 200)

        self.client.force_login(self.cashier)
        for url_name in (
            "commissions_commissionledgerentry_changelist",
            "commissions_commissionpayoutrecord_changelist",
            "commissions_commissionpayoutrequest_changelist",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(f"admin:{url_name}")).status_code, 403)

    def test_commission_ledger_and_payout_records_reject_mutation(self):
        with self.assertRaises(TypeError):
            self.ledger_entry.delete()
        with self.assertRaises(TypeError):
            self.payout_record.delete()
        with self.assertRaises(TypeError):
            CommissionLedgerEntry.objects.filter(pk=self.ledger_entry.pk).update(amount=Decimal("1.00"))
        with self.assertRaises(TypeError):
            CommissionPayoutRecord.objects.filter(pk=self.payout_record.pk).update(amount=Decimal("1.00"))
