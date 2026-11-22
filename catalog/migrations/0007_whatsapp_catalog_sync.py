import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_product_image_service_image_service_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppCatalogSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("retailer_id", models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ("meta_product_item_id", models.CharField(blank=True, max_length=100)),
                ("catalog_linked", models.BooleanField(default=False)),
                ("status", models.CharField(
                    choices=[
                        ("UNLINKED", "Needs Meta catalogue mapping"),
                        ("PENDING", "Waiting to sync"),
                        ("SYNCING", "Synchronising"),
                        ("SYNCED", "Synchronised"),
                        ("FAILED", "Sync failed"),
                    ],
                    default="UNLINKED",
                    max_length=10,
                )),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("last_error", models.TextField(blank=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="whatsapp_catalog_sync", to="catalog.product")),
            ],
            options={"ordering": ("product__name", "product__sku")},
        ),
    ]
