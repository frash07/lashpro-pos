import uuid
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def backfill_fulfilled_order_sales(apps, schema_editor):
    database = schema_editor.connection.alias
    StorefrontOrder = apps.get_model("storefront", "StorefrontOrder")
    StorefrontOrderLine = apps.get_model("storefront", "StorefrontOrderLine")
    Sale = apps.get_model("sales", "Sale")
    SaleLine = apps.get_model("sales", "SaleLine")
    AuditEvent = apps.get_model("audit", "AuditEvent")

    orders = StorefrontOrder.objects.using(database).filter(
        status="FULFILLED",
        sale__isnull=True,
    ).order_by("pk")

    for order in orders.iterator():
        fulfilment_actor_id = None
        events = AuditEvent.objects.using(database).filter(
            object_type="storefront_order",
            object_id=str(order.pk),
        ).order_by("-created_at", "-pk")
        for event in events.iterator():
            if (event.after_state or {}).get("status") == "FULFILLED":
                actor = event.actor
                if actor.is_superuser or actor.role in {"OWNER", "MANAGER", "CASHIER"}:
                    fulfilment_actor_id = event.actor_id
                break
        if fulfilment_actor_id is None:
            # Do not invent a cashier for a legacy row without a fulfilment audit event.
            continue

        order_lines = list(
            StorefrontOrderLine.objects.using(database)
            .filter(order_id=order.pk)
            .order_by("pk")
        )
        if not order_lines:
            continue
        order_total = sum(
            (Decimal(line.quantity) * line.unit_price for line in order_lines),
            Decimal("0.00"),
        )
        if order_total != order.total_amount:
            # Leave inconsistent historical records untouched for manual review.
            continue

        sale_key = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"lashpro:storefront-order:{order.pk}:{order.idempotency_key}",
        )
        sale = Sale.objects.using(database).filter(
            checkout_idempotency_key=sale_key
        ).first()
        if sale is None:
            sale = Sale.objects.using(database).create(
                cashier_id=fulfilment_actor_id,
                customer_id=order.customer_id,
                checkout_idempotency_key=sale_key,
            )
            for order_line in order_lines:
                SaleLine.objects.using(database).create(
                    sale_id=sale.pk,
                    product_id=order_line.product_id,
                    description=order_line.name_snapshot,
                    quantity=order_line.quantity,
                    unit_price=order_line.unit_price,
                    discount=Decimal("0.00"),
                )
            sale.status = "COMPLETED"
            sale.save(using=database, update_fields=("status",))
        else:
            sale_lines = list(
                SaleLine.objects.using(database).filter(sale_id=sale.pk).order_by("pk")
            )
            if sale.status != "COMPLETED" or len(sale_lines) != len(order_lines):
                continue
            valid_lines = all(
                sale_line.product_id == order_line.product_id
                and sale_line.description == order_line.name_snapshot
                and sale_line.quantity == order_line.quantity
                and sale_line.unit_price == order_line.unit_price
                and sale_line.discount == Decimal("0.00")
                for sale_line, order_line in zip(sale_lines, order_lines)
            )
            if not valid_lines:
                continue

        sale_total = sum(
            (
                Decimal(line.quantity) * line.unit_price - line.discount
                for line in SaleLine.objects.using(database).filter(sale_id=sale.pk)
            ),
            Decimal("0.00"),
        )
        if sale.status != "COMPLETED" or sale_total != order.total_amount:
            continue

        order.sale_id = sale.pk
        order.save(using=database, update_fields=("sale",))


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("sales", "0007_guard_sale_records"),
        ("storefront", "0002_stock_reservations"),
    ]

    operations = [
        migrations.AddField(
            model_name="storefrontorder",
            name="sale",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="storefront_order",
                to="sales.sale",
            ),
        ),
        migrations.RunPython(
            backfill_fulfilled_order_sales,
            migrations.RunPython.noop,
        ),
    ]
