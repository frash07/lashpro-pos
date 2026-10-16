from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        CASHIER  = "CASHIER", "Staff"
        TECHNICIAN = "TECHNICIAN", "Lash Technician"
        TRAINER = "TRAINER", "Trainer"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.TECHNICIAN
    )