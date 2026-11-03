from django.contrib import admin
from django.contrib.auth.models import Permission
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_audit_event


class AuditEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="audit-owner", password="x", role=User.Role.OWNER)

    def test_audit_event_cannot_be_changed_or_deleted_through_orm(self):
        event = record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="test", object_id="1", actor=self.owner, reason="Approval test",
        )
        with self.assertRaises(TypeError):
            AuditEvent.objects.filter(pk=event.pk).update(reason="rewritten")
        with self.assertRaises(TypeError):
            event.delete()

    def test_postgres_rejects_direct_audit_event_mutation(self):
        if connection.vendor != "postgresql":
            self.skipTest("Database trigger is PostgreSQL-specific.")
        event = record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="test", object_id="2", actor=self.owner, reason="Trigger test",
        )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE audit_auditevent SET reason = %s WHERE id = %s",
                        ["rewritten", event.pk],
                    )


class AuditEventAdminIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser(
            username="audit-admin-owner",
            email="audit-admin-owner@example.test",
            password="test-password",
            role=User.Role.OWNER,
        )
        cls.manager = User.objects.create_user(
            username="audit-admin-manager",
            password="test-password",
            role=User.Role.MANAGER,
            is_staff=True,
        )
        cls.cashier = User.objects.create_user(
            username="audit-admin-cashier",
            password="test-password",
            role=User.Role.CASHIER,
            is_staff=True,
        )
        cls.manager.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="audit",
                codename="view_auditevent",
            )
        )
        cls.event = record_audit_event(
            event_type=AuditEvent.EventType.APPROVAL,
            object_type="admin_test",
            object_id="phase-7",
            actor=cls.owner,
            reason="People and Access admin integration test.",
        )

    def test_manager_can_review_audit_events_but_cannot_add_or_delete_them(self):
        self.client.force_login(self.manager)
        changelist = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertEqual(changelist.status_code, 200)

        change_url = reverse(
            "admin:audit_auditevent_change",
            args=[self.event.pk],
        )
        change_response = self.client.get(change_url)
        self.assertEqual(change_response.status_code, 200)

        model_admin = admin.site._registry[AuditEvent]
        model_fields = {field.name for field in AuditEvent._meta.fields}
        readonly_fields = set(model_admin.get_readonly_fields(
            change_response.wsgi_request,
            self.event,
        ))
        self.assertTrue(model_fields.issubset(readonly_fields))
        self.assertFalse(model_admin.has_add_permission(change_response.wsgi_request))
        self.assertFalse(model_admin.has_delete_permission(
            change_response.wsgi_request,
            self.event,
        ))

        self.assertEqual(
            self.client.get(reverse("admin:audit_auditevent_add")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse(
                "admin:audit_auditevent_delete",
                args=[self.event.pk],
            )).status_code,
            403,
        )

    def test_cashier_without_audit_view_permission_is_denied(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("admin:audit_auditevent_changelist")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse(
                "admin:audit_auditevent_change",
                args=[self.event.pk],
            )).status_code,
            403,
        )
