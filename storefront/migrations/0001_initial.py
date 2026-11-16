import django.db.models.deletion
import django.utils.timezone
import storefront.models
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0003_alter_user_role"),
        ("catalog", "0006_product_image_service_image_service_kind"),
        ("customers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StorefrontProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("customer", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="storefront_profile", to="customers.customer")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="storefront_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="StorefrontOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(default=storefront.models.generate_order_reference, editable=False, max_length=20, unique=True)),
                ("access_token", models.CharField(default=storefront.models.generate_order_token, editable=False, max_length=64, unique=True)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("customer_name", models.CharField(max_length=100)),
                ("customer_email", models.EmailField(max_length=254)),
                ("customer_phone", models.CharField(max_length=20)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("PLACED", "Awaiting staff confirmation"), ("CONFIRMED", "Confirmed"), ("READY", "Ready for collection"), ("FULFILLED", "Fulfilled"), ("CANCELLED", "Cancelled")], default="PLACED", max_length=12)),
                ("payment_method", models.CharField(choices=[("PAY_AT_STUDIO", "Pay at studio")], default="PAY_AT_STUDIO", max_length=20)),
                ("total_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="storefront_orders", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="storefront_orders", to="customers.customer")),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.CreateModel(
            name="StorefrontOrderLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sku_snapshot", models.CharField(max_length=50)),
                ("name_snapshot", models.CharField(max_length=100)),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=12)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="storefront.storefrontorder")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="storefront_order_lines", to="catalog.product")),
            ],
            options={"ordering": ("pk",)},
        ),
        migrations.AddConstraint(
            model_name="storefrontorderline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gte", 1)), name="storefront_order_line_quantity_positive"),
        ),
        migrations.AddConstraint(
            model_name="storefrontorderline",
            constraint=models.CheckConstraint(condition=models.Q(("line_total__gte", 0)), name="storefront_order_line_total_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="storefrontorderline",
            constraint=models.UniqueConstraint(fields=("order", "product"), name="storefront_order_product_unique"),
        ),
    ]
