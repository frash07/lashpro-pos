import uuid

from django.db import migrations, models


def populate_checkout_keys(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    database = schema_editor.connection.alias
    for sale in Sale.objects.using(database).filter(checkout_idempotency_key__isnull=True).iterator():
        Sale.objects.using(database).filter(pk=sale.pk).update(
            checkout_idempotency_key=uuid.uuid4()
        )


class Migration(migrations.Migration):
    dependencies = [("sales", "0004_saleline_commission_eligible_snapshot_and_more")]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="checkout_idempotency_key",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(populate_checkout_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sale",
            name="checkout_idempotency_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
