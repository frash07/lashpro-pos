from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0010_unique_stk_receipt"),
    ]

    operations = [
        migrations.CreateModel(
            name="MpesaC2BPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("business_shortcode", models.CharField(max_length=20)),
                ("transaction_type", models.CharField(blank=True, max_length=60)),
                ("bill_ref_number", models.CharField(blank=True, max_length=100)),
                ("invoice_number", models.CharField(blank=True, max_length=100)),
                ("payer_first_name", models.CharField(blank=True, max_length=100)),
                ("payer_middle_name", models.CharField(blank=True, max_length=100)),
                ("payer_last_name", models.CharField(blank=True, max_length=100)),
                ("masked_msisdn", models.CharField(blank=True, max_length=32)),
                ("transacted_at", models.DateTimeField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("payment_transaction", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="c2b_payment", to="payments.paymenttransaction")),
            ],
            options={"ordering": ("-received_at", "-pk")},
        ),
    ]
