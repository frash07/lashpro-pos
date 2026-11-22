from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_product_on_hand_product_reorder_level_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="whatsapp_retailer_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("whatsapp_retailer_id", "")),
                fields=("whatsapp_retailer_id",),
                name="catalog_product_whatsapp_retailer_uniq",
            ),
        ),
    ]
