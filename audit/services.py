from .models import AuditEvent


def record_audit_event(
    *, event_type, object_type, object_id, actor, reason="",
    approver=None, before_state=None, after_state=None, metadata=None,
):
    return AuditEvent.objects.create(
        event_type=event_type,
        object_type=object_type,
        object_id=str(object_id),
        actor=actor,
        approver=approver,
        reason=reason,
        before_state=before_state or {},
        after_state=after_state or {},
        metadata=metadata or {},
    )
