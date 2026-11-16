from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner"),
                    ("MANAGER", "Manager"),
                    ("CASHIER", "Staff"),
                    ("TECHNICIAN", "Lash Technician"),
                    ("TRAINER", "Trainer"),
                    ("CUSTOMER", "Customer"),
                ],
                default="TECHNICIAN",
                max_length=10,
            ),
        ),
    ]
