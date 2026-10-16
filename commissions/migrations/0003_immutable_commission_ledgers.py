from django.db import migrations


def install_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_commission_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Commission ledger records are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table, trigger in (
        ("commissions_commissionledgerentry", "commission_ledger_entry_immutable"),
        ("commissions_commissionpayoutrecord", "commission_payout_record_immutable"),
    ):
        schema_editor.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_commission_ledger_mutation()")


def remove_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, trigger in (
        ("commissions_commissionledgerentry", "commission_ledger_entry_immutable"),
        ("commissions_commissionpayoutrecord", "commission_payout_record_immutable"),
    ):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_prevent_commission_ledger_mutation()")


class Migration(migrations.Migration):
    dependencies = [("commissions", "0002_initial")]
    operations = [migrations.RunPython(install_triggers, remove_triggers)]
