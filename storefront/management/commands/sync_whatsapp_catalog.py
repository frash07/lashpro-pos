from django.core.management.base import BaseCommand

from storefront.whatsapp import retry_catalog_sync


class Command(BaseCommand):
    help = "Queue or retry WhatsApp catalogue publication using the current Neon product and stock data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-products",
            action="store_true",
            help="Queue every product for a full Meta catalogue reconciliation before dispatch.",
        )

    def handle(self, *args, **options):
        retry_catalog_sync(all_products=options["all_products"])
        self.stdout.write(
            self.style.SUCCESS(
                "WhatsApp catalogue sync queue processed. Check Admin → WhatsApp catalogue sync "
                "for items that still need attention."
            )
        )
