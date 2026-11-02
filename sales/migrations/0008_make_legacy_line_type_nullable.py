from django.db import migrations


class Migration(migrations.Migration):
    """
    Make the legacy, database-only sales_saleline.line_type column nullable.

    Current SaleLine records are classified by product_id/service_id. The
    production database still has an older NOT NULL line_type column which
    is not represented in Django's model state. Keeping the column and its
    existing values avoids data loss; allowing NULL lets current ORM inserts
    succeed without inventing a classification value.
    """

    dependencies = [
        ("sales", "0007_guard_sale_records"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "DO $$ BEGIN "
                "IF EXISTS ("
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'sales_saleline' "
                "AND column_name = 'line_type' "
                "AND is_nullable = 'NO'"
                ") THEN "
                "ALTER TABLE sales_saleline ALTER COLUMN line_type DROP NOT NULL; "
                "END IF; "
                "END $$;"
            ),
            # Intentionally do not restore NOT NULL: new rows may now contain
            # NULL, and restoring it would make rollback fail or require data
            # rewriting. The legacy column and all existing values are kept.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
