# Generated for the expenses register.
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("audit", "0006_alter_auditevent_event_type"),
        ("payments", "0008_guard_payment_records"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("expense_date", models.DateField(default=django.utils.timezone.localdate)),
                ("category", models.CharField(choices=[
                    ("RENT", "Rent"), ("UTILITIES", "Utilities"), ("SALON_SUPPLIES", "Salon supplies"),
                    ("MARKETING", "Marketing"), ("TRANSPORT", "Transport"),
                    ("MAINTENANCE", "Repairs and maintenance"), ("STAFF", "Staff costs"),
                    ("INTERNET", "Internet and communications"), ("PROFESSIONAL", "Professional fees"),
                    ("BANK_CHARGES", "Bank charges"), ("OTHER", "Other"),
                ], max_length=20)),
                ("description", models.CharField(max_length=500)),
                ("supplier", models.CharField(blank=True, max_length=160)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("payment_status", models.CharField(choices=[("PAID", "Paid"), ("UNPAID", "Unpaid")], default="PAID", max_length=10)),
                ("payment_method", models.CharField(blank=True, choices=[("CASH", "Cash"), ("MPESA", "M-Pesa"), ("BANK", "Bank transfer")], max_length=10)),
                ("reference", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cash_movement", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_record", to="payments.cashsessionmovement")),
                ("cash_session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expenses", to="payments.cashsession")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses_recorded", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-expense_date", "-created_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="expense",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="expense_amount_positive"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["expense_date", "category"], name="expense_date_category_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["payment_status", "expense_date"], name="expense_status_date_idx"),
        ),
    ]
