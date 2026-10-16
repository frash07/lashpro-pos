from django.db import models

# Create your models here.

class Organization(models.Model):
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=50, default="Africa/Nairobi")
    currency = models.CharField(max_length=10, default="KES")
    receipt_prefix = models.CharField(max_length=20, default="LP")

class BusinessSettings(models.Model):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE
    )

    opening_time = models.TimeField()
    closing_time = models.TimeField()

    default_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=40.00
    )


