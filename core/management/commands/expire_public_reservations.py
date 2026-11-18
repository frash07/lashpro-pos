from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from appointments.services import expire_due_requested_appointments
from core.models import PublicRateLimitBucket
from storefront.services import expire_due_storefront_orders


class Command(BaseCommand):
    help = "Expire stale unconfirmed storefront orders and appointment holds."

    def handle(self, *args, **options):
        now = timezone.now()
        orders = expire_due_storefront_orders(limit=1000)
        appointments = expire_due_requested_appointments(limit=1000)
        deleted, _details = PublicRateLimitBucket.objects.filter(
            updated_at__lt=now - timedelta(days=2)
        ).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Expired {orders} online order(s) and {appointments} appointment request(s); "
            f"removed {deleted} stale rate-limit bucket(s)."
        ))
