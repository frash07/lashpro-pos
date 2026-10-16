from django.db import migrations


def install_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_payment_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Cash and payout ledger records are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table, trigger in (
        ("payments_cashsessionmovement", "cash_session_movement_immutable"),
        ("payments_refundpayout", "refund_payout_immutable"),
        ("payments_payoutreconciliation", "payout_reconciliation_immutable"),
    ):
        schema_editor.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_payment_ledger_mutation()")


def remove_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, trigger in (
        ("payments_cashsessionmovement", "cash_session_movement_immutable"),
        ("payments_refundpayout", "refund_payout_immutable"),
        ("payments_payoutreconciliation", "payout_reconciliation_immutable"),
    ):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_prevent_payment_ledger_mutation()")


class Migration(migrations.Migration):
    dependencies = [("payments", "0004_cashsession_paymenttransaction_cash_session_and_more")]
    operations = [migrations.RunPython(install_triggers, remove_triggers)]
