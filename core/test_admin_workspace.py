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
from training.models import Assessment, Cohort, Course, TrainingSession


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
        for app in ("accounts", "appointments", "audit", "axes", "inventory", "catalog", "commissions", "customers", "expenses", "storefront", "sales", "training", "payments"):
            with self.subTest(app=app):
                self.assert_workspace(self.client.get(reverse("admin:app_list", kwargs={"app_label": app})), "index")

    def test_all_requested_registers(self):
        for register in (
            "accounts_user", "appointments_appointment", "appointments_staffavailability",
            "appointments_stafftimeoff", "audit_auditevent", "auth_group",
            "axes_accesslog", "axes_accessattempt", "axes_accessfailurelog",
            "inventory_supplier", "inventory_stockreceipt", "inventory_stockadjustmentrequest",
            "inventory_serviceconsumable", "inventory_inventorymovement",
            "catalog_service", "commissions_commissionpayoutrequest",
            "commissions_commissionpayoutrecord", "commissions_commissionledgerentry",
            "customers_customer", "expenses_expense", "storefront_whatsappinboundorder",
            "storefront_whatsappcatalogsync", "storefront_storefrontorder",
            "sales_sale", "sales_salerefund", "sales_saleline",
            "training_course", "training_cohort", "training_trainingsession", "training_enrollment",
            "training_assessment", "training_assessmentresult", "training_attendance", "training_certificate",
            "payments_cashsession", "payments_cashsessionmovement", "payments_mpesac2bpayment",
            "payments_mpesastkpush", "payments_paymentreconciliation", "payments_paymenttransaction",
            "payments_salepayment", "payments_refundpayout", "payments_payoutreconciliation",
        ):
            with self.subTest(register=register):
                self.assert_workspace(self.client.get(reverse("admin:" + register + "_changelist")), "change_list")

    def test_requested_forms_and_edit_links(self):
        for register in ("auth_group", "inventory_supplier", "inventory_stockadjustmentrequest", "inventory_serviceconsumable", "catalog_service", "catalog_product", "customers_customer", "training_course", "training_cohort", "training_trainingsession", "training_assessment"):
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

    def test_operational_commissions_and_reconciliation_share_workspace(self):
        for name, template in (("commissions:dashboard", "commissions/dashboard.html"),
                               ("payments:reconciliation", "payments/reconciliation.html")):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                self.assertTemplateUsed(response, "admin_workspace/base.html")
                self.assertContains(response, static("css/admin-workspace.css"))
                self.assertNotContains(response, static("admin/css/base.css"))
        response = self.client.get(reverse("commissions:dashboard"))
        self.assertContains(response, 'name="action" value="request"')
        self.assertContains(response, 'name="technician"')
        self.assertContains(response, "Commission balances by lash technician")

    def test_nonstaff_technician_retains_self_service_only(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("commissions:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Available balance")
        self.assertNotContains(response, 'name="technician"')
        self.assertNotContains(response, "Commission balances by lash technician")
        self.assertNotContains(response, reverse("admin:index"))
        self.assertEqual(self.client.get(reverse("payments:reconciliation")).status_code, 403)

    def test_new_catalogue_forms_keep_backend_fields(self):
        product = self.client.get(reverse("admin:catalog_product_add"))
        self.assert_workspace(product, "change_form")
        self.assertContains(product, 'name="sku"')
        self.assertContains(product, 'name="selling_price"')
        self.assertContains(product, 'enctype="multipart/form-data"')
        self.assertNotContains(product, 'name="on_hand"')
        service = self.client.get(reverse("admin:catalog_service_add"))
        self.assert_workspace(service, "change_form")
        self.assertContains(service, 'name="price"')
        self.assertContains(service, 'name="duration_minutes"')


    def test_academy_creation_and_autocomplete(self):
        course_url = reverse("admin:training_course_add")
        response = self.client.post(course_url, {"code": "UI-101", "name": "Workspace course",
            "duration_days": "5", "tuition_fee": "2500", "minimum_attendance_percent": "80",
            "is_active": "on", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        course = Course.objects.get(code="UI-101")
        trainer = get_user_model().objects.create_user(username="workspace-trainer", role="TRAINER", password="x")
        today = timezone.localdate()
        end = today + timedelta(days=5)
        cohort_url = reverse("admin:training_cohort_add")
        response = self.client.get(cohort_url)
        self.assert_workspace(response, "change_form")
        self.assertContains(response, "admin-autocomplete")
        self.assertContains(response, static("admin/css/vendor/select2/select2.min.css"))
        response = self.client.post(cohort_url, {"course": course.pk, "trainer": trainer.pk,
            "name": "Workspace cohort", "start_date": today.isoformat(), "end_date": end.isoformat(),
            "capacity": "12", "status": Cohort.Status.PLANNED, "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        cohort = Cohort.objects.get(course=course)
        for model, name, data in (
            (Assessment, "assessment", {"title": "Practice assessment", "max_score": "100",
                "passing_score": "80", "due_at_0": "", "due_at_1": ""}),
            (TrainingSession, "trainingsession", {"title": "Practice session",
                "starts_at_0": today.isoformat(), "starts_at_1": "09:00:00",
                "ends_at_0": today.isoformat(), "ends_at_1": "10:00:00"}),
        ):
            with self.subTest(name=name):
                url = reverse("admin:training_" + name + "_add")
                page = self.client.get(url)
                self.assert_workspace(page, "change_form")
                formsets = page.context["inline_admin_formsets"]
                for inline in formsets:
                    prefix = inline.formset.prefix
                    data.update({prefix + "-TOTAL_FORMS": "0", prefix + "-INITIAL_FORMS": "0",
                        prefix + "-MIN_NUM_FORMS": "0", prefix + "-MAX_NUM_FORMS": "0"})
                response = self.client.post(url, {"cohort": cohort.pk, "_save": "Save", **data})
                self.assertEqual(response.status_code, 302)
                obj = model.objects.get(cohort=cohort)
                self.assertEqual(obj.created_by, self.owner)
                self.assert_workspace(self.client.get(reverse("admin:training_" + name + "_change", args=[obj.pk])), "change_form")

    def test_read_only_payment_and_academy_registers(self):
        for name in ("training_attendance", "training_assessmentresult", "training_certificate",
                     "training_enrollment", "payments_paymenttransaction", "payments_cashsession",
                     "payments_cashsessionmovement", "payments_salepayment", "payments_mpesac2bpayment",
                     "payments_mpesastkpush", "payments_paymentreconciliation", "payments_refundpayout",
                     "payments_payoutreconciliation"):
            with self.subTest(name=name):
                response = self.client.get(reverse("admin:" + name + "_changelist"))
                self.assert_workspace(response, "change_list")
                self.assertFalse(response.context["has_add_permission"])
                self.assertEqual(self.client.get(reverse("admin:" + name + "_add")).status_code, 403)
        viewer = get_user_model().objects.create_user(username="workspace-training-viewer", is_staff=True, password="x")
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="training", codename="view_course"))
        self.client.force_login(viewer)
        self.assert_workspace(self.client.get(reverse("admin:training_course_changelist")), "change_list")
        self.assertEqual(self.client.get(reverse("admin:training_course_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:payments_paymenttransaction_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reporting:dashboard")).status_code, 403)
