import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0005_product_catalog_image_metadata"),
        ("storefront", "0004_public_reservation_expiry"),
    ]

    operations = [
        migrations.AddField(
            model_name="storefrontorder",
            name="source_channel",
            field=models.CharField(
                choices=[("STOREFRONT", "Online storefront"), ("WHATSAPP", "WhatsApp catalogue")],
                db_index=True,
                default="STOREFRONT",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="storefrontorder",
            name="external_order_id",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddConstraint(
            model_name="storefrontorder",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("external_order_id", "")),
                fields=("source_channel", "external_order_id"),
                name="storefront_channel_order_unique",
            ),
        ),
        migrations.CreateModel(
            name="WhatsAppInboundOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=255, unique=True)),
                ("sender_id", models.CharField(max_length=32)),
                ("customer_name", models.CharField(blank=True, max_length=100)),
                ("catalog_id", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(
                    choices=[("IMPORTED", "Imported into online orders"), ("NEEDS_REVIEW", "Needs staff review")],
                    default="NEEDS_REVIEW",
                    max_length=16,
                )),
                ("issue", models.CharField(blank=True, max_length=500)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("order", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="whatsapp_imports",
                    to="storefront.storefrontorder",
                )),
            ],
            options={"ordering": ("-received_at", "-pk")},
        ),
        migrations.CreateModel(
            name="WhatsAppCatalogSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("retailer_id", models.CharField(max_length=50, unique=True)),
                ("status", models.CharField(
                    choices=[("PENDING", "Pending"), ("SYNCED", "Synced"), ("FAILED", "Failed")],
                    db_index=True,
                    default="PENDING",
                    max_length=10,
                )),
                ("remote_product_id", models.CharField(blank=True, max_length=100)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="whatsapp_catalog_syncs",
                    to="catalog.product",
                )),
            ],
            options={"ordering": ("status", "updated_at", "pk")},
        ),
    ]
