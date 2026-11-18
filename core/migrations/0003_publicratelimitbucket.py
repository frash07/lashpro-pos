from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0002_integrationsettings")]

    operations = [
        migrations.CreateModel(
            name="PublicRateLimitBucket",
            fields=[
                ("key_hash", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("scope", models.CharField(max_length=48)),
                ("window_started_at", models.DateTimeField()),
                ("request_count", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="publicratelimitbucket",
            index=models.Index(fields=["updated_at"], name="core_rate_bucket_age_idx"),
        ),
    ]
