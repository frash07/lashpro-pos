from pathlib import PurePosixPath
from urllib.request import urlopen
from uuid import uuid4

import cloudinary
import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils

from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage


class CloudinaryMediaStorage(Storage):
    """Store Django ImageField uploads in Cloudinary and serve their CDN URLs.

    The POS app uses CLOUDINARY_URL for signed uploads. The storefront app
    only needs CLOUDINARY_CLOUD_NAME to build public delivery URLs.
    """

    def _public_id(self, name):
        return PurePosixPath(name).with_suffix("").as_posix()

    def _save(self, name, content):
        path = PurePosixPath(name)
        stem = path.stem or "upload"
        parent = path.parent.as_posix()
        unique_stem = f"{stem}-{uuid4().hex}"
        public_id = f"{parent}/{unique_stem}" if parent != "." else unique_stem

        result = cloudinary.uploader.upload(
            content,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
            unique_filename=False,
            use_filename=False,
        )
        uploaded_id = result["public_id"]
        uploaded_format = result.get("format") or path.suffix.lstrip(".")
        return f"{uploaded_id}.{uploaded_format}" if uploaded_format else uploaded_id

    def _open(self, name, mode="rb"):
        if mode not in {"rb", "r"}:
            raise ValueError("Cloudinary media can only be opened for reading.")
        with urlopen(self.url(name), timeout=20) as response:
            return ContentFile(response.read(), name=PurePosixPath(name).name)

    def delete(self, name):
        public_id = self._public_id(name)
        cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)

    def exists(self, name):
        try:
            cloudinary.api.resource(self._public_id(name), resource_type="image")
        except cloudinary.exceptions.NotFound:
            return False
        return True

    def size(self, name):
        resource = cloudinary.api.resource(self._public_id(name), resource_type="image")
        return int(resource.get("bytes", 0))

    def url(self, name):
        config = cloudinary.config()
        if not config.cloud_name:
            raise ImproperlyConfigured(
                "Set CLOUDINARY_URL on the POS app or CLOUDINARY_CLOUD_NAME "
                "on the storefront app before requesting image URLs."
            )

        path = PurePosixPath(name)
        public_id = self._public_id(name)
        image_format = path.suffix.lstrip(".") or None
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            format=image_format,
            resource_type="image",
            secure=True,
        )
        return url
