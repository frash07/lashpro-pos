from django.db import migrations


def install_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_prevent_inventory_movement_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Inventory movements are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER inventory_movement_immutable
        BEFORE UPDATE OR DELETE ON inventory_inventorymovement
        FOR EACH ROW EXECUTE FUNCTION lashpro_prevent_inventory_movement_mutation();
    """)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS inventory_movement_immutable ON inventory_inventorymovement")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_prevent_inventory_movement_mutation()")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    operations = [migrations.RunPython(install_trigger, remove_trigger)]
