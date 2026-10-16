import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User


class Command(BaseCommand):
    help = "Create the first owner account during deployment when credentials are configured."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_BOOTSTRAP_OWNER_USERNAME", "").strip()
        email = os.environ.get("DJANGO_BOOTSTRAP_OWNER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_BOOTSTRAP_OWNER_PASSWORD", "")

        values = (username, email, password)
        if not any(values):
            self.stdout.write("No bootstrap owner credentials configured; skipping.")
            return
        if not all(values):
            raise CommandError(
                "Set all three DJANGO_BOOTSTRAP_OWNER_USERNAME, "
                "DJANGO_BOOTSTRAP_OWNER_EMAIL, and DJANGO_BOOTSTRAP_OWNER_PASSWORD "
                "values, or remove all three."
            )

        existing = User.objects.filter(username=username).first()
        if existing:
            if (
                existing.is_superuser
                and existing.is_staff
                and existing.role == User.Role.OWNER
            ):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Bootstrap owner {username!r} already exists; leaving it unchanged."
                    )
                )
                return
            raise CommandError(
                f"Username {username!r} already belongs to a non-owner account; "
                "no account was changed."
            )

        candidate = User(username=username, email=email)
        try:
            validate_password(password, user=candidate)
        except ValidationError as exc:
            raise CommandError(
                "The bootstrap password does not meet Django's password policy."
            ) from exc

        with transaction.atomic():
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                role=User.Role.OWNER,
            )

        self.stdout.write(
            self.style.SUCCESS(f"Created the initial owner account {username!r}.")
        )
