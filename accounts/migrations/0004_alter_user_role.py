from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_user_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner"),
                    ("MANAGER", "Manager"),
                    ("CASHIER", "Cashier"),
                    ("TECHNICIAN", "Lash Technician"),
                    ("TRAINER", "Trainer"),
                    ("CUSTOMER", "Customer"),
                ],
                default="TECHNICIAN",
                max_length=10,
            ),
        ),
    ]
