from django.db import migrations, models
from django.db.models import Q


def mark_existing_service_lines(apps, schema_editor):
    SaleLine = apps.get_model("sales", "SaleLine")
    SaleLine.objects.filter(service__isnull=False).update(line_type="SERVICE")


def install_line_guard(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
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
            IF (NEW.sale_id, NEW.product_id, NEW.service_id, NEW.line_kind, NEW.description,
                NEW.quantity, NEW.unit_price, NEW.discount,
                NEW.commission_eligible_snapshot, NEW.commission_rate_snapshot)
               IS DISTINCT FROM
               (OLD.sale_id, OLD.product_id, OLD.service_id, OLD.line_kind, OLD.description,
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


def restore_line_guard(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
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


def remove_catalog_item_constraint_if_present(apps, schema_editor):
    """Remove the pre-training line constraint when it exists in the database."""
    SaleLine = apps.get_model("sales", "SaleLine")
    constraint_name = "sales_line_exactly_one_catalog_item"

    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor, SaleLine._meta.db_table
        )

    if constraint_name not in constraints:
        return

    schema_editor.remove_constraint(
        SaleLine,
        models.CheckConstraint(
            condition=(
                Q(product__isnull=False, service__isnull=True)
                | Q(product__isnull=True, service__isnull=False)
            ),
            name=constraint_name,
        ),
    )


def restore_catalog_item_constraint(apps, schema_editor):
    """Restore the pre-training line constraint when rolling this migration back."""
    SaleLine = apps.get_model("sales", "SaleLine")
    constraint_name = "sales_line_exactly_one_catalog_item"

    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor, SaleLine._meta.db_table
        )

    if constraint_name in constraints:
        return

    schema_editor.add_constraint(
        SaleLine,
        models.CheckConstraint(
            condition=(
                Q(product__isnull=False, service__isnull=True)
                | Q(product__isnull=True, service__isnull=False)
            ),
            name=constraint_name,
        ),
    )

class Migration(migrations.Migration):
    dependencies = [("sales", "0008_make_legacy_line_type_nullable")]

    operations = [
        migrations.AddField(
            model_name="saleline",
            name="line_type",
            field=models.CharField(
                choices=[("PRODUCT", "Retail product"), ("SERVICE", "Salon service"), ("TRAINING", "Training tuition")],
                db_column="line_kind",
                default="PRODUCT",
                max_length=12,
            ),
        ),
        migrations.RunPython(mark_existing_service_lines, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    remove_catalog_item_constraint_if_present,
                    restore_catalog_item_constraint,
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="saleline",
                    name="sales_line_exactly_one_catalog_item",
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="saleline",
            constraint=models.CheckConstraint(
                condition=(
                    Q(line_type="PRODUCT", product__isnull=False, service__isnull=True)
                    | Q(line_type="SERVICE", product__isnull=True, service__isnull=False)
                    | Q(line_type="TRAINING", product__isnull=True, service__isnull=True)
                ),
                name="sales_line_matches_item_type",
            ),
        ),
        migrations.RunPython(install_line_guard, restore_line_guard),
    ]
