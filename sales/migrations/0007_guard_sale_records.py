from django.db import migrations


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_completed_sale()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Completed sale records cannot be deleted';
            END IF;
            IF (NEW.receipt_number, NEW.receipt_token, NEW.checkout_idempotency_key,
                NEW.customer_id, NEW.cashier_id, NEW.created_at)
               IS DISTINCT FROM
               (OLD.receipt_number, OLD.receipt_token, OLD.checkout_idempotency_key,
                OLD.customer_id, OLD.cashier_id, OLD.created_at) THEN
                RAISE EXCEPTION 'Sale identity and customer snapshots are immutable';
            END IF;
            IF OLD.status <> 'DRAFT' OR NEW.status <> 'COMPLETED' THEN
                RAISE EXCEPTION 'Sale status can only transition from draft to completed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER sale_record_guard
        BEFORE UPDATE OR DELETE ON sales_sale
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_completed_sale();
    """)
    schema_editor.execute("""
        CREATE OR REPLACE FUNCTION lashpro_guard_sale_line_snapshot()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM sales_sale
                    WHERE id = NEW.sale_id AND status = 'DRAFT'
                ) THEN
                    RAISE EXCEPTION 'Sale lines can only be added to a draft sale';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Sale lines cannot be deleted';
            END IF;
            IF (NEW.sale_id, NEW.product_id, NEW.service_id, NEW.description,
                NEW.quantity, NEW.unit_price, NEW.discount,
                NEW.commission_eligible_snapshot, NEW.commission_rate_snapshot)
               IS DISTINCT FROM
               (OLD.sale_id, OLD.product_id, OLD.service_id, OLD.description,
                OLD.quantity, OLD.unit_price, OLD.discount,
                OLD.commission_eligible_snapshot, OLD.commission_rate_snapshot) THEN
                RAISE EXCEPTION 'Sale line financial snapshots are immutable';
            END IF;
            IF OLD.technician_id IS DISTINCT FROM NEW.technician_id
               AND NOT (
                   OLD.technician_id IS NULL
                   AND NEW.technician_id IS NOT NULL
                   AND OLD.service_completed_at IS NULL
                   AND NEW.service_completed_at IS NOT NULL
               ) THEN
                RAISE EXCEPTION 'Technician assignment is immutable after checkout';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    schema_editor.execute("""
        CREATE TRIGGER sale_line_snapshot_guard
        BEFORE INSERT OR UPDATE OR DELETE ON sales_saleline
        FOR EACH ROW EXECUTE FUNCTION lashpro_guard_sale_line_snapshot();
    """)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS sale_record_guard ON sales_sale")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_completed_sale()")
    schema_editor.execute("DROP TRIGGER IF EXISTS sale_line_snapshot_guard ON sales_saleline")
    schema_editor.execute("DROP FUNCTION IF EXISTS lashpro_guard_sale_line_snapshot()")


class Migration(migrations.Migration):
    dependencies = [("sales", "0006_remove_saleline_sales_line_not_both_catalog_items_and_more")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
