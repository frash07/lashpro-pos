# Shared product image storage on Fly.io

Product and service images are uploaded through Django's admin. The database stores the image path, while the image bytes must be stored somewhere both Fly apps can read.

The previous default stored files under `/code/media` on the POS machine. That filesystem is not shared with `lashpro-storefront`, is not durable across machine replacement, and production URL configuration does not serve Django's `/media/` route. The application now supports a public Tigris bucket as its default media storage when `BUCKET_NAME` is configured.

## 1. Create one public bucket

Run this once from the repository directory:

```sh
fly storage create --public -a lashpro-pos
```

Choose a bucket name when prompted and keep a record of it. Fly sets the Tigris S3 credentials, endpoint, and `BUCKET_NAME` secret on `lashpro-pos`. The bucket must be public because product images are public storefront content.

For a bucket that already exists, do not create another bucket just for the storefront. Change its access setting to public in the Tigris/Fly storage dashboard if it is private.

## 2. Point the storefront app at the same bucket

The storefront app must use the exact same bucket name. Set the bucket name on the second Fly app:

```sh
fly secrets set BUCKET_NAME="<your-bucket-name>" -a lashpro-storefront
```

The code derives the public image host as `<your-bucket-name>.t3.tigrisfiles.io`. If you use a custom domain for Tigris, set `MEDIA_PUBLIC_DOMAIN` to that hostname on **both** Fly apps:

```sh
fly secrets set MEDIA_PUBLIC_DOMAIN="<your-media-domain>" -a lashpro-pos
fly secrets set MEDIA_PUBLIC_DOMAIN="<your-media-domain>" -a lashpro-storefront
```

The storefront only needs the bucket name to render public image URLs. Keep the S3 access key and secret on the POS app, where staff upload images. Do not commit either key to Git.

## 3. Deploy the same code to both apps

Deploy this branch to `lashpro-pos` and `lashpro-storefront`. Both apps must run the same version of `config/settings.py` and have the same `BUCKET_NAME` (and, if configured, `MEDIA_PUBLIC_DOMAIN`).

## 4. Preserve any images already uploaded to the old local filesystem

Files previously uploaded to `/code/media` are not automatically copied to Tigris. Back up the old POS machine's catalog directory **before deploying**, while the old machine is still running:

```sh
fly ssh sftp get /code/media/catalog ./catalog-media-backup --recursive -a lashpro-pos
```

After the new version and bucket secrets are deployed, restore that backup onto the POS machine and run the migration command:

```sh
fly ssh console -a lashpro-pos
mkdir -p /code/media/catalog
exit
fly ssh sftp put ./catalog-media-backup /code/media/catalog --recursive -a lashpro-pos
fly ssh console -a lashpro-pos
python manage.py copy_local_media_to_tigris
```

This command copies product/service images from the restored local directory into Tigris without deleting the local originals. It is safe to run again: objects already present in the bucket are skipped. If the command reports missing local files, restore the correct directory structure from your backup or upload the images again through Django admin.

If the old machine has already been replaced and no backup exists, the database may still contain image paths but the actual image files may no longer exist. In that case, re-upload those images.

## 5. Verify

1. In `https://lashpro-pos.fly.dev/admin/`, open a product and upload an image.
2. Save, then confirm the image link points to the Tigris public domain and opens directly.
3. Open `https://lashpro-storefront.fly.dev/`; the matching product card should display the same image.
4. Add the image to the cart and confirm it still displays there.

New uploads are stored in the shared bucket, so the admin and storefront apps no longer depend on local machine files.
