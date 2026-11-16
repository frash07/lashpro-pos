from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from core.storage import CloudinaryMediaStorage


class CloudinaryMediaStorageTests(SimpleTestCase):
    @patch("core.storage.CloudinaryMediaStorage.exists", return_value=False)
    @patch("core.storage.cloudinary.uploader.upload")
    def test_save_uses_unique_cloudinary_public_id(self, upload, _exists):
        upload.side_effect = lambda content, **kwargs: {
            "public_id": kwargs["public_id"],
            "format": "jpg",
        }
        storage = CloudinaryMediaStorage()

        saved_name = storage.save("catalog/glue.jpg", ContentFile(b"image-bytes"))

        self.assertTrue(saved_name.startswith("catalog/glue-"))
        self.assertTrue(saved_name.endswith(".jpg"))
        upload.assert_called_once()
        self.assertEqual(upload.call_args.kwargs["resource_type"], "image")
        self.assertFalse(upload.call_args.kwargs["overwrite"])

    @patch("core.storage.cloudinary.config")
    @patch("core.storage.cloudinary.utils.cloudinary_url")
    def test_url_uses_public_cloud_name_and_https(self, build_url, config):
        config.return_value = SimpleNamespace(cloud_name="lashpro")
        build_url.return_value = ("https://res.cloudinary.com/lashpro/image/upload/catalog/glue.jpg", {})

        result = CloudinaryMediaStorage().url("catalog/glue.jpg")

        self.assertEqual(
            result,
            "https://res.cloudinary.com/lashpro/image/upload/catalog/glue.jpg",
        )
        self.assertEqual(build_url.call_args.kwargs["secure"], True)
