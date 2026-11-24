from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0009_mpesa_stk_push"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="mpesastkpush",
            constraint=models.UniqueConstraint(
                Lower("mpesa_receipt_number"),
                condition=~Q(mpesa_receipt_number=""),
                name="mpesa_stk_receipt_ci_unique",
            ),
        ),
    ]
