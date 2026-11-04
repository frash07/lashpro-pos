# Supplier receipts are posted as immutable receipt documents with stock-ledger lines.
import uuid

import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_serviceconsumable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("contact_person", models.CharField(blank=True, max_length=120)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("name",),
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        name="inventory_supplier_name_ci_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference_type", models.CharField(
                    choices=[
                        ("INVOICE", "Supplier invoice"),
                        ("DELIVERY_NOTE", "Delivery note"),
                        ("CASH_RECEIPT", "Cash receipt"),
                        ("OTHER", "Other supplier document"),
                    ],
                    default="INVOICE",
                    max_length=20,
                )),
                ("supplier_reference", models.CharField(max_length=100)),
                ("delivery_note_number", models.CharField(blank=True, max_length=100)),
                ("received_date", models.DateField(default=django.utils.timezone.localdate)),
                ("notes", models.TextField(blank=True)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("received_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_stock_receipts",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("supplier", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="stock_receipts",
                    to="inventory.supplier",
                )),
            ],
            options={
                "ordering": ("-received_date", "-created_at", "-pk"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("supplier", "reference_type", "supplier_reference"),
                        name="inventory_supplier_receipt_reference_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockReceiptLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12)),
                ("unit_cost", models.DecimalField(decimal_places=2, max_digits=10)),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="supplier_receipt_lines",
                    to="catalog.product",
                )),
                ("receipt", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="lines",
                    to="inventory.stockreceipt",
                )),
            ],
            options={
                "ordering": ("pk",),
                "constraints": [
                    models.UniqueConstraint(fields=("receipt", "product"), name="inventory_receipt_product_uniq"),
                    models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="inventory_receipt_quantity_positive"),
                    models.CheckConstraint(condition=models.Q(("unit_cost__gte", 0)), name="inventory_receipt_cost_nonnegative"),
                ],
            },
        ),
        migrations.AddField(
            model_name="inventorymovement",
            name="receipt_line",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movement",
                to="inventory.stockreceiptline",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventorymovement",
            constraint=models.CheckConstraint(
                condition=models.Q(("receipt_line__isnull", True), ("movement_type", "PURCHASE"), _connector="OR"),
                name="inventory_receipt_line_purchase_only",
            ),
        ),
    ]
