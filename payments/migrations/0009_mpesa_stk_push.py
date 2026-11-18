from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0008_guard_payment_records"),
    ]

    operations = [
        migrations.CreateModel(
            name="MpesaStkPush",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("callback_token", models.CharField(max_length=96, unique=True)),
                ("phone_number", models.CharField(max_length=16)),
                ("merchant_request_id", models.CharField(blank=True, max_length=100)),
                ("checkout_request_id", models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ("status", models.CharField(choices=[("PENDING", "Prompt sent"), ("UNKNOWN", "Awaiting callback confirmation"), ("SUCCEEDED", "Paid"), ("FAILED", "Failed")], default="PENDING", max_length=12)),
                ("result_code", models.CharField(blank=True, max_length=20)),
                ("result_description", models.CharField(blank=True, max_length=500)),
                ("mpesa_receipt_number", models.CharField(blank=True, max_length=50)),
                ("callback_payload", models.JSONField(blank=True, default=dict)),
                ("callback_received_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payment_transaction", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="stk_push", to="payments.paymenttransaction")),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
    ]
