from django.db import migrations


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_product_sku()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.sku IS DISTINCT FROM OLD.sku THEN
                RAISE EXCEPTION 'Product SKUs are permanent and cannot be changed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER product_sku_immutable_guard
        BEFORE UPDATE OF sku ON catalog_product
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_product_sku();
    """)
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_sku_reservation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Issued SKU reservations cannot be deleted';
            END IF;
            IF NEW.sku IS DISTINCT FROM OLD.sku
               OR (NEW.product_id IS DISTINCT FROM OLD.product_id
                   AND NOT (OLD.product_id IS NOT NULL AND NEW.product_id IS NULL)) THEN
                RAISE EXCEPTION 'Issued SKU reservations are permanent';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER sku_reservation_immutable_guard
        BEFORE UPDATE OR DELETE ON catalog_skureservation
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_sku_reservation();
    """)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS product_sku_immutable_guard ON catalog_product")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_product_sku()")
    schema_editor.execute("DROP TRIGGER IF EXISTS sku_reservation_immutable_guard ON catalog_skureservation")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_sku_reservation()")


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_skureservation")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
