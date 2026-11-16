import django.db.models.deletion
import uuid
import appointments.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0003_alter_user_role"),
        ("catalog", "0006_product_image_service_image_service_kind"),
        ("customers", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffAvailability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("weekday", models.PositiveSmallIntegerField(choices=[(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")])),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="appointment_availability", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("weekday", "start_time", "staff__last_name", "staff__first_name")},
        ),
        migrations.CreateModel(
            name="StaffTimeOff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("reason", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_appointment_time_off", to=settings.AUTH_USER_MODEL)),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="appointment_time_off", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("starts_at", "staff__last_name")},
        ),
        migrations.CreateModel(
            name="Appointment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(default=appointments.models.generate_appointment_reference, editable=False, max_length=20, unique=True)),
                ("access_token", models.CharField(default=appointments.models.generate_appointment_token, editable=False, max_length=64, unique=True)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("service_name_snapshot", models.CharField(max_length=100)),
                ("duration_minutes_snapshot", models.PositiveIntegerField()),
                ("price_snapshot", models.DecimalField(decimal_places=2, max_digits=10)),
                ("customer_name", models.CharField(max_length=100)),
                ("customer_email", models.EmailField(max_length=254)),
                ("customer_phone", models.CharField(max_length=20)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("REQUESTED", "Awaiting confirmation"), ("CONFIRMED", "Confirmed"), ("CANCELLED", "Cancelled"), ("COMPLETED", "Completed"), ("NO_SHOW", "No-show")], default="REQUESTED", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_appointments", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="customers.customer")),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="appointments", to="catalog.service")),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assigned_appointments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("starts_at", "staff__last_name", "pk")},
        ),
        migrations.AddConstraint(
            model_name="staffavailability",
            constraint=models.UniqueConstraint(fields=("staff", "weekday"), name="appt_staff_day_unique"),
        ),
        migrations.AddConstraint(
            model_name="staffavailability",
            constraint=models.CheckConstraint(condition=models.Q(("start_time__lt", models.F("end_time"))), name="appt_avail_time_order"),
        ),
        migrations.AddConstraint(
            model_name="staffavailability",
            constraint=models.CheckConstraint(condition=models.Q(("weekday__gte", 0), ("weekday__lte", 6)), name="appt_avail_day_range"),
        ),
        migrations.AddConstraint(
            model_name="stafftimeoff",
            constraint=models.CheckConstraint(condition=models.Q(("ends_at__gt", models.F("starts_at"))), name="appt_timeoff_order"),
        ),
        migrations.AddIndex(
            model_name="stafftimeoff",
            index=models.Index(fields=["staff", "starts_at", "ends_at"], name="appt_timeoff_staff_idx"),
        ),
        migrations.AddConstraint(
            model_name="appointment",
            constraint=models.CheckConstraint(condition=models.Q(("ends_at__gt", models.F("starts_at"))), name="appt_end_after_start"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["staff", "starts_at", "ends_at"], name="appt_staff_start_idx"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["status", "starts_at"], name="appt_status_start_idx"),
        ),
    ]
