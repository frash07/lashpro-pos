# Storefront preview on Fly.io

This preview is deliberately separate from the pilot application. It deploys `main` to `lashpro-storefront-preview.fly.dev`, with its own PostgreSQL database and synthetic-only sample records. The production storefront also deploys from `main` to `lashpro-storefront.fly.dev` using `fly.storefront.toml` and a separate Fly app-scoped token.

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
| `FLY_API_TOKEN` | The app-scoped token created in step 3 |
| `PREVIEW_DATABASE_URL` | Connection URL for the separate, empty PostgreSQL database; use TLS (`sslmode=require`) |
| `PREVIEW_DJANGO_SECRET_KEY` | A unique, strong Django secret key used only by the preview |
| `PREVIEW_STAFF_PASSWORD` | A strong, test-only password for the synthetic staff users created by the seed command |

No organization-wide Fly token is needed by the GitHub workflow. The `lashpro-storefront-preview` app must exist before the first deployment.

The existing Django CI workflow first runs dependency checks, Django checks, migration checks, static collection, tests, and a production Docker build. On pushes to `main`, it then deploys the isolated preview first when its secrets are configured, followed by the production storefront when `FLY_STOREFRONT_API_TOKEN` is configured. The preview uses `FLY_API_TOKEN` (scoped to the preview app); production uses a separate `FLY_STOREFRONT_API_TOKEN` (scoped to `lashpro-storefront`). If either token is missing, that deployment is skipped with a notice. The POS app continues to deploy separately using `fly.toml`.

## Database options and costs

A dedicated Fly Managed Postgres cluster can be used for `PREVIEW_DATABASE_URL`. Fly's October 2026 preview-environment guidance lists the Basic Managed Postgres plan at about US$38/month plus storage; verify current pricing before creating paid resources. A separate test database from another PostgreSQL provider can also be used, provided it is isolated from the pilot database and reachable from Fly.io.

If you use Fly Managed Postgres, create a separate cluster in the Fly dashboard or with `fly mpg create`, then obtain its connection URL for the GitHub `PREVIEW_DATABASE_URL` secret. Do not attach the production cluster.

## Preview URL

Once the CI workflow passes and the configuration is complete:

https://lashpro-storefront-preview.fly.dev

The preview contains synthetic catalog data, not a copy of the live pilot catalogue. The storefront code reads products and services from the preview database, exactly as the production site will read from its own configured database. A later, separate task can add a controlled catalogue-only import for selected real product/service records, without copying customer or sales data.
