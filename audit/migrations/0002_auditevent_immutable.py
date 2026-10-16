from django.db import migrations


def install_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Audit events are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER audit_event_immutable
        BEFORE UPDATE OR DELETE ON audit_auditevent
        FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_audit_event_mutation();
    """)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS audit_event_immutable ON audit_auditevent")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_prevent_audit_event_mutation()")


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunPython(install_trigger, remove_trigger)]
