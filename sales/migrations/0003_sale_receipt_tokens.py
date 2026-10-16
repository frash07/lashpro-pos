import secrets

from django.db import migrations, models
import sales.models


def populate_receipt_identifiers(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    db_alias = schema_editor.connection.alias
    numbers, tokens = set(), set()
    for sale in Sale.objects.using(db_alias).all().iterator():
        number = "LP-" + secrets.token_hex(5).upper()
        while number in numbers:
            number = "LP-" + secrets.token_hex(5).upper()
        token = secrets.token_urlsafe(32)
        while token in tokens:
            token = secrets.token_urlsafe(32)
        numbers.add(number)
        tokens.add(token)
        sale.receipt_number, sale.receipt_token = number, token
        sale.save(update_fields=("receipt_number", "receipt_token"))


class Migration(migrations.Migration):
    dependencies = [("sales", "0002_alter_sale_options_saleline_product_saleline_service_and_more")]

    operations = [
        migrations.AddField(model_name="sale", name="receipt_number", field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AddField(model_name="sale", name="receipt_token", field=models.CharField(blank=True, max_length=64, null=True)),
        migrations.RunPython(populate_receipt_identifiers, migrations.RunPython.noop),
        migrations.AlterField(model_name="sale", name="receipt_number", field=models.CharField(default=sales.models.generate_receipt_number, editable=False, max_length=20, unique=True)),
        migrations.AlterField(model_name="sale", name="receipt_token", field=models.CharField(default=sales.models.generate_receipt_token, editable=False, max_length=64, unique=True)),
    ]
