import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0003_publicratelimitbucket")]

    operations = [
        migrations.CreateModel(
            name="SharedDatabaseProbe",
            fields=[
                (
                    "token",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
        migrations.AddIndex(
            model_name="shareddatabaseprobe",
            index=models.Index(fields=["expires_at"], name="core_db_probe_expiry_idx"),
        ),
    ]
