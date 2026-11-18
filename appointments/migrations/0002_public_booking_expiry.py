from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone

import appointments.models


def backfill_appointment_expiry(apps, schema_editor):
    database = schema_editor.connection.alias
    Appointment = apps.get_model("appointments", "Appointment")
    now = timezone.now()
    for appointment in Appointment.objects.using(database).all().iterator():
        # Start the new hold policy after deployment; give existing pending
        # requests a full grace window rather than expiring them at migration.
        expires_at = now + timedelta(minutes=30)
        appointment.expires_at = expires_at
        if appointment.status == "REQUESTED" and expires_at <= now:
            appointment.status = "EXPIRED"
            appointment.expired_at = now
        appointment.save(using=database, update_fields=("expires_at", "status", "expired_at"))


class Migration(migrations.Migration):
    dependencies = [("appointments", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="appointment",
            name="status",
            field=models.CharField(
                choices=[
                    ("REQUESTED", "Awaiting confirmation"),
                    ("CONFIRMED", "Confirmed"),
                    ("CANCELLED", "Cancelled"),
                    ("COMPLETED", "Completed"),
                    ("NO_SHOW", "No-show"),
                    ("EXPIRED", "Expired — slot released"),
                ],
                default="REQUESTED",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="appointment",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="appointment",
            name="expired_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_appointment_expiry, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="appointment",
            name="expires_at",
            field=models.DateTimeField(db_index=True, default=appointments.models.default_booking_expiry),
        ),
    ]
