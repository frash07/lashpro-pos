# Storefront preview on Fly.io

This preview is deliberately separate from the pilot application. It deploys the `storefront` branch to `lashpro-storefront-preview.fly.dev`, with its own PostgreSQL database and synthetic-only sample records.

## Safety boundary

- Do **not** set `PREVIEW_DATABASE_URL` to the pilot's `DATABASE_URL` or `DATABASE_URL_DIRECT`.
- Use a fresh, disposable PostgreSQL database for the preview. No pilot customers, sales, payments, inventory movements, or staff records are copied.
- The preview release runs migrations and the existing guarded `seed_synthetic_data` command. That command verifies the exact database name before inserting fictional products, services, customers, staff and example test transactions.
- The preview points its Staff login link at the existing pilot POS URL. This does not deploy code to or change the pilot app.
- The preview app autostops when idle (`min_machines_running = 0`).

## GitHub repository configuration

Add these repository **secrets** under Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `FLY_API_TOKEN` | Fly.io organization-scoped token with permission to create/update the preview app |
| `PREVIEW_DATABASE_URL` | Connection URL for a separate, empty PostgreSQL database; use TLS (`sslmode=require`) |
| `PREVIEW_DJANGO_SECRET_KEY` | A unique, strong Django secret key used only by the preview |
| `PREVIEW_STAFF_PASSWORD` | A strong, test-only password for the synthetic staff users created by the seed command |

Add this repository **variable**:

| Variable | Value |
|---|---|
| `FLY_ORG` | Fly.io organization slug that owns the preview app |

The existing Django CI workflow first runs the dependency checks, Django checks, migration checks, static collection and tests. Only after those steps pass on the `storefront` branch does it attempt the preview deployment. If the secrets and variable are not configured, it records a notice and skips deployment without failing CI.

## Database options and costs

A dedicated Fly Managed Postgres cluster can be used for `PREVIEW_DATABASE_URL`. Fly's October 2026 preview-environment guidance lists the Basic Managed Postgres plan at about US$38/month plus storage; verify current pricing before creating paid resources. A separate test database from another PostgreSQL provider can also be used, provided it is isolated from the pilot database and reachable from Fly.io.

To use Fly Managed Postgres, create a separate cluster in the Fly dashboard or with `fly mpg create`, then obtain its connection URL for the GitHub `PREVIEW_DATABASE_URL` secret. Do not attach the production cluster.

## Preview URL

Once the CI workflow passes and the configuration is complete:

https://lashpro-storefront-preview.fly.dev

The app URL assumes that name is available in Fly.io. If it is already taken, change the `app` name in `fly.storefront-preview.toml`, the `APP` value in `.github/workflows/ci.yml`, and the hostname values in that TOML file together.

The preview contains synthetic catalog data, not a copy of the live pilot catalogue. The storefront code reads products and services from the preview database, exactly as the production site will read from its own configured database. A later, separate task can add a controlled catalogue-only import for selected real product/service records, without copying customer or sales data.
