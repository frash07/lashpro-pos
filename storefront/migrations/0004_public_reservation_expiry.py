from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone

import storefront.models


def backfill_order_expiry(apps, schema_editor):
    database = schema_editor.connection.alias
    Order = apps.get_model("storefront", "StorefrontOrder")
    Reservation = apps.get_model("storefront", "StorefrontStockReservation")
    now = timezone.now()
    expired_ids = []
    for order in Order.objects.using(database).filter(status="PLACED").iterator():
        expires_at = order.created_at + timedelta(minutes=30)
        order.expires_at = expires_at
        if expires_at <= now:
            order.status = "EXPIRED"
            order.expired_at = now
            expired_ids.append(order.pk)
        order.save(using=database, update_fields=("expires_at", "status", "expired_at"))
    if expired_ids:
        Reservation.objects.using(database).filter(
            order_line__order_id__in=expired_ids,
            status="ACTIVE",
        ).update(status="RELEASED", released_at=now)


class Migration(migrations.Migration):
    dependencies = [("storefront", "0003_storefrontorder_sale")]

    operations = [
        migrations.AddField(
            model_name="storefrontorder",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="storefrontorder",
            name="expired_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_order_expiry, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="storefrontorder",
            name="expires_at",
            field=models.DateTimeField(db_index=True, default=storefront.models.default_order_expiry),
        ),
    ]
