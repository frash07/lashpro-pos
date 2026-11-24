from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment, StaffAvailability
from catalog.models import Product, Service
from inventory.models import Supplier


class StandaloneAdminWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_superuser(
            username="workspace-owner", email="workspace@example.test",
            password="test-password", role=User.Role.OWNER,
        )
        cls.staff = User.objects.create_user(
            username="workspace-artist", password="test-password", role=User.Role.TECHNICIAN,
        )
        cls.product = Product.objects.create(
            sku="WORKSPACE-01", name="Workspace adhesive", cost_price=Decimal("100"),
            selling_price=Decimal("200"), on_hand=Decimal("3"),
        )
        cls.service = Service.objects.create(
            name="Workspace lash service", duration_minutes=60, price=Decimal("1000"),
        )
        cls.availability = StaffAvailability.objects.create(
            staff=cls.staff, weekday=1, start_time=time(9), end_time=time(17),
        )
        starts = timezone.now() + timedelta(days=2)
        cls.appointment = Appointment.objects.create(
            service=cls.service, staff=cls.staff, service_name_snapshot=cls.service.name,
            duration_minutes_snapshot=60, price_snapshot=Decimal("1000"),
            customer_name="Workspace customer", customer_email="customer@example.test",
            customer_phone="0700000000", starts_at=starts, ends_at=starts + timedelta(hours=1),
            status=Appointment.Status.CONFIRMED,
        )
        cls.supplier = Supplier.objects.create(name="Workspace supplier")

    def setUp(self):
        self.client.force_login(self.owner)

    def assert_workspace(self, response, template):
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin_workspace/" + template + ".html")
        self.assertContains(response, 'class="admin-suite-body checkout-page product-workspace standalone-admin"')
        self.assertContains(response, static("css/tokens.css"))
        self.assertContains(response, static("sales/checkout-workspace.css"))
        self.assertContains(response, static("css/admin-workspace.css"))
        self.assertNotContains(response, 'id="nav-sidebar"')
        self.assertNotContains(response, static("admin/css/base.css"))

    def test_all_requested_indexes(self):
        self.assert_workspace(self.client.get(reverse("admin:index")), "index")
        for app in ("accounts", "appointments", "audit", "axes", "inventory"):
            with self.subTest(app=app):
                self.assert_workspace(self.client.get(reverse("admin:app_list", kwargs={"app_label": app})), "index")

    def test_all_requested_registers(self):
        for register in (
            "accounts_user", "appointments_appointment", "appointments_staffavailability",
            "appointments_stafftimeoff", "audit_auditevent", "auth_group",
            "axes_accesslog", "axes_accessattempt", "axes_accessfailurelog",
            "inventory_supplier", "inventory_stockreceipt", "inventory_stockadjustmentrequest",
            "inventory_serviceconsumable", "inventory_inventorymovement",
        ):
            with self.subTest(register=register):
                self.assert_workspace(self.client.get(reverse("admin:" + register + "_changelist")), "change_list")

    def test_requested_forms_and_edit_links(self):
        for register in ("auth_group", "inventory_supplier", "inventory_stockadjustmentrequest", "inventory_serviceconsumable"):
            with self.subTest(register=register):
                self.assert_workspace(self.client.get(reverse("admin:" + register + "_add")), "change_form")
        for register, obj in (("appointments_staffavailability", self.availability), ("appointments_appointment", self.appointment)):
            with self.subTest(register=register):
                self.assert_workspace(self.client.get(reverse("admin:" + register + "_change", args=[obj.pk])), "change_form")

    def test_native_supplier_post_and_validation(self):
        url = reverse("admin:inventory_supplier_add")
        invalid = self.client.post(url, {"name": "", "_save": "Save"})
        self.assert_workspace(invalid, "change_form")
        self.assertContains(invalid, "Review the highlighted fields.")
        response = self.client.post(url, {"name": "Workspace new supplier", "active": "on", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Supplier.objects.filter(name="Workspace new supplier").exists())

    def test_group_permissions_post(self):
        permission = Permission.objects.get(content_type__app_label="inventory", codename="view_supplier")
        response = self.client.post(reverse("admin:auth_group_add"), {
            "name": "Workspace group", "permissions": [permission.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Group.objects.get(name="Workspace group").permissions.all()), [permission])

    def test_search_and_permission_boundaries(self):
        response = self.client.get(reverse("admin:inventory_supplier_changelist"), {"q": "Workspace supplier"})
        self.assert_workspace(response, "change_list")
        self.assertContains(response, "Workspace supplier")
        user = get_user_model().objects.create_user(username="workspace-viewer", password="x", is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="inventory", codename="view_supplier"))
        self.client.force_login(user)
        response = self.client.get(reverse("admin:inventory_supplier_changelist"))
        self.assert_workspace(response, "change_list")
        self.assertNotContains(response, reverse("admin:inventory_supplier_add"))
        self.assertEqual(self.client.get(reverse("admin:inventory_supplier_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_group_changelist")).status_code, 403)

    def test_popup_and_product_workspace_are_not_intercepted(self):
        response = self.client.get(reverse("admin:inventory_supplier_changelist"), {"_popup": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, "admin_workspace/change_list.html")
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateNotUsed(response, "admin_workspace/change_list.html")
        self.assertContains(response, 'id="product-grid"')
