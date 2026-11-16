# Product image storage using Cloudinary

The POS and storefront are separate Fly.io applications. Uploaded product images therefore need shared storage rather than either app's local machine filesystem.

Cloudinary is the temporary no-card option for this deployment. Its Free plan is listed at $0 with no credit card required and includes 25 monthly credits shared across storage, transformations and image bandwidth. Check current usage in the Cloudinary console; the free allowance is not unlimited.

## 1. Create a Cloudinary Free account

Register at https://cloudinary.com/users/register/free.

In the Cloudinary Console, open **Settings → API Keys**. Copy the `CLOUDINARY_URL` value shown by Cloudinary. It contains the API key, API secret and cloud name.

Treat `CLOUDINARY_URL` as a password. Do not commit it, put it in source code, or send it in chat.

## 2. Configure Fly secrets

The POS app needs the full URL because it accepts and uploads images:

```powershell
fly secrets set CLOUDINARY_URL="cloudinary://API_KEY:API_SECRET@CLOUD_NAME" -a lashpro-pos
```

The storefront only needs the public cloud name to build image delivery URLs. It does not need the API key or API secret:

```powershell
fly secrets set CLOUDINARY_CLOUD_NAME="CLOUD_NAME" -a lashpro-storefront
```

Replace the placeholders with the values from the Cloudinary console. Do not set `CLOUDINARY_CLOUD_NAME` on the POS app when using `CLOUDINARY_URL`; the Cloudinary SDK treats individually supplied Cloudinary variables as overrides for the URL.

## 3. Deploy the same code to both Fly apps

Merge the image-storage pull request, then deploy the updated code to both apps:

```powershell
fly deploy -a lashpro-pos
fly deploy --config fly.storefront.toml -a lashpro-storefront
```

Both apps must run the same revision of the application code. The POS stores uploaded images in Cloudinary; the storefront builds public CDN URLs using the cloud name.

## 4. Re-upload the five recovered product images

The database still has the old filenames, but the files on the previous Fly machine could not be found. Those old database references do not mean the corresponding files exist in Cloudinary.

After the updated POS app is deployed, open `https://lashpro-pos.fly.dev/admin/` and edit each product. Upload the matching local file from your Downloads folder:

| Product | Local file |
|---|---|
| Lash Training Strips | `lash_trainging_strips.jpg` |
| Lash Tray | `Lash_Tray.jpg` |
| Glue | `glue.jpg` |
| Spoolies | `spoolies.png` |
| Tape | `tapeee.jpg` |

The Dummy product has no recovered image. It can remain without an image until its original is found.

## 5. Verify

1. Save a product after choosing its image in the admin.
2. Confirm the admin preview loads from `res.cloudinary.com`.
3. Open `https://lashpro-storefront.fly.dev/` and check the corresponding product card.
4. Add the product to the cart and verify that its image loads there too.

New uploads are now stored outside Fly machines, so both apps can display the same image and machine restarts no longer remove the uploaded files.
