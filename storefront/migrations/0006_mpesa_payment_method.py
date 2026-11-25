from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("storefront", "0005_whatsapp_commerce")]

    operations = [
        migrations.AlterField(
            model_name="storefrontorder",
            name="payment_method",
            field=models.CharField(
                choices=[("PAY_AT_STUDIO", "Pay at studio"), ("MPESA", "M-Pesa STK Push")],
                default="PAY_AT_STUDIO", max_length=20,
            ),
        ),
    ]
