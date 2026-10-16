from django.db import DatabaseError, connection, transaction
from django.test import TestCase

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
