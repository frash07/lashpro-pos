from django.db import migrations


def install_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_payment_reconciliation_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Payment reconciliation records are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER payment_reconciliation_immutable
        BEFORE UPDATE OR DELETE ON payments_paymentreconciliation
        FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_payment_reconciliation_mutation();
    """)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS payment_reconciliation_immutable ON payments_paymentreconciliation")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_prevent_payment_reconciliation_mutation()")


class Migration(migrations.Migration):
    dependencies = [("payments", "0005_immutable_cash_and_payout_ledgers")]
    operations = [migrations.RunPython(install_trigger, remove_trigger)]
