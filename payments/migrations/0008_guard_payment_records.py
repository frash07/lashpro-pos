from django.db import migrations


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_payment_transaction()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Payment transactions cannot be deleted';
            END IF;
            IF (NEW.amount, NEW.method, NEW.reference, NEW.idempotency_key,
                NEW.recorded_by_id, NEW.cash_session_id, NEW.created_at)
               IS DISTINCT FROM
               (OLD.amount, OLD.method, OLD.reference, OLD.idempotency_key,
                OLD.recorded_by_id, OLD.cash_session_id, OLD.created_at) THEN
                RAISE EXCEPTION 'Payment transaction details are immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NOT (
                   (OLD.status = 'UNVERIFIED' AND NEW.status IN ('SUCCEEDED', 'FAILED'))
                   OR (
                       OLD.status = 'PENDING'
                       AND NEW.status = 'CANCELLED'
                       AND OLD.method = 'CASH'
                       AND OLD.cash_session_id IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM payments_salepayment sp
                           WHERE sp.payment_transaction_id = OLD.id
                       )
                       AND EXISTS (
                           SELECT 1 FROM audit_auditevent ae
                           WHERE ae.event_type = 'APPROVAL'
                             AND ae.object_type = 'abandoned_payment'
                             AND ae.object_id = OLD.id::text
                             AND ae.before_state ->> 'status' = 'PENDING'
                             AND ae.after_state ->> 'status' = 'CANCELLED'
                             AND ae.metadata ->> 'payment_id' = OLD.id::text
                       )
                   )
               ) THEN
                RAISE EXCEPTION 'Payment status can only change through reconciliation or audited orphan cancellation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER payment_transaction_guard
        BEFORE UPDATE OR DELETE ON payments_paymenttransaction
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_payment_transaction();
    """)
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_sale_payment_allocation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Sale payment allocations are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER sale_payment_allocation_guard
        BEFORE UPDATE OR DELETE ON payments_salepayment
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_sale_payment_allocation();
    """)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS payment_transaction_guard ON payments_paymenttransaction")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_payment_transaction()")
    schema_editor.execute("DROP TRIGGER IF EXISTS sale_payment_allocation_guard ON payments_salepayment")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_sale_payment_allocation()")


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0007_paymenttransaction_idempotency_key_and_more"),
        ("sales", "0006_remove_saleline_sales_line_not_both_catalog_items_and_more"),
    ]
    operations = [migrations.RunPython(install_guards, remove_guards)]
