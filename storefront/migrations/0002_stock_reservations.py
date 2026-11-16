import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_product_image_service_image_service_kind"),
        ("storefront", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StorefrontStockReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("status", models.CharField(choices=[("ACTIVE", "Reserved"), ("CONSUMED", "Fulfilled"), ("RELEASED", "Released")], default="ACTIVE", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("order_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="stock_reservation", to="storefront.storefrontorderline")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="storefront_stock_reservations", to="catalog.product")),
            ],
            options={"ordering": ("created_at", "pk")},
        ),
        migrations.AddConstraint(
            model_name="storefrontstockreservation",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="storefront_reservation_quantity_positive"),
        ),
    ]
