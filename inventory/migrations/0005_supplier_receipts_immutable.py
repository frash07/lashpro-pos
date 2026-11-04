from django.db import migrations


def install_receipt_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_supplier_receipt_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Supplier receipts are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER supplier_stock_receipt_immutable
        BEFORE UPDATE OR DELETE ON inventory_stockreceipt
        FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_supplier_receipt_mutation();
    """)
    schema_editor.execute("""
        CREATE TRIGGER supplier_stock_receipt_line_immutable
        BEFORE UPDATE OR DELETE ON inventory_stockreceiptline
        FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_supplier_receipt_mutation();
    """)


def remove_receipt_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS supplier_stock_receipt_line_immutable ON inventory_stockreceiptline"
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS supplier_stock_receipt_immutable ON inventory_stockreceipt"
    )
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS lashpro_prevent_supplier_receipt_mutation()"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_supplier_receipts"),
    ]

    operations = [
        migrations.RunPython(install_receipt_guards, remove_receipt_guards),
    ]
