import json
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from core.models import SharedDatabaseProbe


class Command(BaseCommand):
    help = (
        "Create or verify a short-lived record across the LashPro POS and "
        "storefront databases without displaying connection credentials."
    )

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("create", "verify"))
        parser.add_argument(
            "--token",
            help="One-time token printed by the create action.",
        )

    def _database_identity(self):
        if connection.vendor != "postgresql":
            raise CommandError(
                "Shared database verification requires the production PostgreSQL database."
            )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            )
            connected_name, server_address, server_port = cursor.fetchone()

        configured = connection.settings_dict
        return {
            "configured_host": configured.get("HOST") or "(default)",
            "configured_port": configured.get("PORT") or "(default)",
            "configured_database": configured.get("NAME"),
            "connected_database": connected_name,
            "server_address": server_address or "(local socket)",
            "server_port": server_port,
        }

    def handle(self, *args, **options):
        action = options["action"]
        now = timezone.now()
        identity = self._database_identity()

        if action == "create":
            # Remove abandoned challenges before adding a new 30-minute marker.
            SharedDatabaseProbe.objects.filter(expires_at__lte=now).delete()
            probe = SharedDatabaseProbe.objects.create(
                expires_at=now + timedelta(minutes=30),
            )
            self.stdout.write(json.dumps({
                "status": "created",
                "token": str(probe.token),
                "expires_at": probe.expires_at.isoformat(),
                "database": identity,
                "next_step": (
                    "Run the verify action against the other Fly app and pass this token."
                ),
            }, sort_keys=True))
            return

        raw_token = (options.get("token") or "").strip()
        if not raw_token:
            raise CommandError("The verify action requires --token.")

        try:
            token = uuid.UUID(raw_token)
        except (ValueError, TypeError, AttributeError) as exc:
            raise CommandError("--token must be a valid UUID from the create action.") from exc

        with transaction.atomic():
            probe = (
                SharedDatabaseProbe.objects.select_for_update()
                .filter(token=token, expires_at__gt=now)
                .first()
            )
            if probe is None:
                raise CommandError(
                    "The live probe was not found in this database. The apps may use "
                    "different databases, or the 30-minute probe may have expired."
                )
            # Consume the one-time row so no handover test data is left behind.
            probe.delete()

        self.stdout.write(json.dumps({
            "status": "verified",
            "shared_record_visible": True,
            "probe_consumed": True,
            "database": identity,
        }, sort_keys=True))
