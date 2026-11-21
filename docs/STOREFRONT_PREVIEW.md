# Storefront preview on Fly.io

This preview is deliberately separate from the pilot application. It deploys `main` to `lashpro-storefront-preview.fly.dev`, with its own PostgreSQL database and synthetic-only sample records. Production deploys the POS and storefront from the same tested `main` revision to `lashpro-pos.fly.dev` and `lashpro-storefront.fly.dev`, using separate app-scoped tokens and one shared production database.

## Safety boundary

- Do **not** set `PREVIEW_DATABASE_URL` to the pilot's `DATABASE_URL` or `DATABASE_URL_DIRECT`.
- Use a fresh, disposable PostgreSQL database for the preview. No pilot customers, sales, payments, inventory movements, or staff records are copied.
- The preview release runs migrations and the existing guarded `seed_synthetic_data` command. That command verifies the exact database name before inserting fictional products, services, customers, staff and example test transactions.
- The preview points its Staff login link at the existing pilot POS URL. This does not deploy code to or change the pilot app.
- The preview app autostops when idle (`min_machines_running = 0`).

## One-time Fly.io setup

1. Create the preview app in the same Fly organization as the pilot, using your own Fly CLI login:

   ```bash
   fly apps create lashpro-storefront-preview --org YOUR_FLY_ORG
   ```

   App names are global on Fly.io. If this name is unavailable, choose another name and update the `app`, host and preview workflow values consistently.

2. Create or choose a **separate empty PostgreSQL database** for the preview. Do not attach the pilot database. A Fly Managed Postgres cluster is one option; another PostgreSQL provider is also acceptable if it permits secure connections from Fly.io.

3. Create an app-scoped deploy token for this preview app:

   ```bash
   fly tokens create deploy -a lashpro-storefront-preview -x 720h
   ```

   Copy the token output directly into the GitHub secret below. This token is limited to the preview app, not the pilot app. It expires after 30 days; rotate it before expiry to keep automatic previews deploying.

## GitHub repository configuration

Under GitHub repository Settings → Secrets and variables → Actions, add these repository **secrets**:

| Secret | Value |
|---|---|
| `FLY_API_TOKEN` | App-scoped deploy token for `lashpro-storefront-preview` (created in step 3) |
| `FLY_POS_API_TOKEN` | App-scoped deploy token for the production `lashpro-pos` app |
| `FLY_STOREFRONT_API_TOKEN` | Separate app-scoped deploy token for the production `lashpro-storefront` app |
| `PREVIEW_DATABASE_URL` | Connection URL for the separate, empty PostgreSQL database; use TLS (`sslmode=require`) |
| `PREVIEW_DJANGO_SECRET_KEY` | A unique, strong Django secret key used only by the preview |
| `PREVIEW_STAFF_PASSWORD` | A strong, test-only password for the synthetic staff users created by the seed command |

No organization-wide Fly token is needed by the GitHub workflow. Keep the preview token separate from each production app token. Create the storefront production token with:

```bash
fly tokens create deploy -a lashpro-storefront -x 720h
```

Create a separate POS token with:

```bash
fly tokens create deploy -a lashpro-pos -x 720h
```

Add the storefront and POS token outputs as the GitHub Actions secrets `FLY_STOREFRONT_API_TOKEN` and `FLY_POS_API_TOKEN`. The preview, POS and storefront Fly apps must exist before their respective deployments.

The existing Django CI workflow first runs dependency checks, Django checks, migration checks, static collection, tests, and a production Docker build. On pushes to `main`, it deploys the isolated preview first when its secrets are configured. Production deployment is enabled only when both production app tokens are present. The workflow deploys POS first with `fly.toml`, then storefront with `fly.storefront.toml`; if either release fails, the next deploy does not run. This keeps the two apps on the same tested revision and prevents concurrent migration commands against their shared database. If either token is missing, both production deployments are skipped with a notice. The preview uses only `FLY_API_TOKEN` and its isolated database.

## Database options and costs

A dedicated Fly Managed Postgres cluster can be used for `PREVIEW_DATABASE_URL`. Fly's October 2026 preview-environment guidance lists the Basic Managed Postgres plan at about US$38/month plus storage; verify current pricing before creating paid resources. A separate test database from another PostgreSQL provider can also be used, provided it is isolated from the pilot database and reachable from Fly.io.

If you use Fly Managed Postgres, create a separate cluster in the Fly dashboard or with `fly mpg create`, then obtain its connection URL for the GitHub `PREVIEW_DATABASE_URL` secret. Do not attach the production cluster.

## Preview URL

Once the CI workflow passes and the configuration is complete:

https://lashpro-storefront-preview.fly.dev

The preview contains synthetic catalog data, not a copy of the live pilot catalogue. The storefront code reads products and services from the preview database, exactly as the production site will read from its own configured database. A later, separate task can add a controlled catalogue-only import for selected real product/service records, without copying customer or sales data.


## Production storefront prerequisites

Before adding either production deploy token, configure both production Fly apps with their own required secrets and verify that both `DATABASE_URL` values connect to the same production database. The storefront needs its own `DJANGO_SECRET_KEY` and public durable-media settings. Do not reuse the preview database or point either app at an empty or synthetic database.

The GitHub workflow deploys the tested `main` commit to POS and then storefront. It does not set or overwrite Fly secrets. Both Fly release commands run Django deployment checks and migrations; keep them serialized and verify the production database backup and credentials before enabling automatic deployment.

The POS app remains separate and continues to use `fly.toml`. The isolated preview continues to use `fly.storefront-preview.toml`.
