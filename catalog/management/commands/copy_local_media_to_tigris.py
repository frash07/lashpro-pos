from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product, Service


class Command(BaseCommand):
    help = "Copy product and service images from MEDIA_ROOT into configured shared object storage."

    def handle(self, *args, **options):
        if not settings.MEDIA_STORAGE_BUCKET_NAME:
            raise CommandError(
                "BUCKET_NAME is not configured. Set up the shared Tigris bucket first."
            )

        uploaded = 0
        already_present = 0
        missing = 0
        media_root = Path(settings.MEDIA_ROOT).resolve()

        for model in (Product, Service):
            for record in model.objects.exclude(image="").exclude(image__isnull=True).iterator():
                key = PurePosixPath(record.image.name)
                if key.is_absolute() or ".." in key.parts:
                    self.stderr.write(f"Skipped unsafe media path: {record.image.name}")
                    missing += 1
                    continue

                object_name = key.as_posix()
                if default_storage.exists(object_name):
                    already_present += 1
                    continue

                local_path = (media_root / Path(*key.parts)).resolve()
                if media_root not in local_path.parents or not local_path.is_file():
                    self.stderr.write(
                        f"Local file is not present for {model.__name__} #{record.pk}: {object_name}"
                    )
                    missing += 1
                    continue

                with local_path.open("rb") as source:
                    saved_name = default_storage.save(
                        object_name,
                        File(source, name=key.name),
                    )
                if saved_name != object_name:
                    self.stderr.write(
                        f"Uploaded {object_name} as {saved_name} because the object name already existed."
                    )
                uploaded += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Media copy complete: {uploaded} uploaded, "
                f"{already_present} already in object storage, {missing} missing locally."
            )
        )
        if missing:
            self.stderr.write(
                "Some image files were not found on this machine. Restore them from a backup "
                "or upload them again in the product/service admin."
            )
