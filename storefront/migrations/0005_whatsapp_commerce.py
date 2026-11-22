import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("storefront", "0004_public_reservation_expiry"),
    ]

    operations = [
        migrations.AlterField(
            model_name="storefrontorder",
            name="customer_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="storefrontorder",
            name="source_channel",
            field=models.CharField(
                choices=[("STOREFRONT", "Online storefront"), ("WHATSAPP", "WhatsApp")],
                default="STOREFRONT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="storefrontorder",
            name="external_reference",
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="WhatsAppOrderInbox",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=128, unique=True)),
                ("sender_phone", models.CharField(max_length=20)),
                ("customer_name", models.CharField(blank=True, max_length=100)),
                ("catalog_id", models.CharField(max_length=100)),
                ("order_payload", models.JSONField()),
                ("status", models.CharField(
                    choices=[
                        ("PENDING", "Waiting to import"),
                        ("PROCESSING", "Import in progress"),
                        ("IMPORTED", "Imported into online orders"),
                        ("FAILED", "Needs review"),
                    ],
                    default="PENDING",
                    max_length=10,
                )),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("last_error", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="whatsapp_imports", to="storefront.storefrontorder")),
            ],
            options={"ordering": ("-received_at", "-pk")},
        ),
    ]
