import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_supplier_receipts_immutable"),
        ("storefront", "0002_stock_reservations"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventorymovement",
            name="storefront_order_line",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_movement", to="storefront.storefrontorderline"),
        ),
        migrations.AlterField(
            model_name="inventorymovement",
            name="movement_type",
            field=models.CharField(choices=[("PURCHASE", "Purchase receipt"), ("SALE", "Product sale"), ("RETURN", "Customer return"), ("SERVICE_USE", "Service consumable"), ("ADJUSTMENT", "Approved adjustment"), ("REVERSAL", "Reversal"), ("ONLINE_ORDER", "Online order fulfilment")], max_length=20),
        ),
        migrations.AddConstraint(
            model_name="inventorymovement",
            constraint=models.CheckConstraint(condition=(models.Q(("movement_type", "ONLINE_ORDER"), ("storefront_order_line__isnull", False)) | (~models.Q(("movement_type", "ONLINE_ORDER")) & models.Q(("storefront_order_line__isnull", True)))), name="inventory_online_order_link_required"),
        ),
    ]
