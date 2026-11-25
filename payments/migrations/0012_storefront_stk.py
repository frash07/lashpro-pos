from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0011_mpesa_c2b_payment"),
        ("storefront", "0006_mpesa_payment_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="mpesastkpush",
            name="storefront_order",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="mpesa_pushes", to="storefront.storefrontorder",
            ),
        ),
    ]
