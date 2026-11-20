# LashPro POS production deployment — Fly.io

This is the canonical production deployment guide for the `lashpro-pos` Fly.io application defined by `fly.toml`. It replaces the old Render Free + Neon Free instructions.

**Production boundary:** Do not use the Render Free Blueprint (`render.yaml`) for live customer records, payments, inventory, or business-critical operations. It is retained only as a disposable synthetic-data test environment. Fly.io and the database provider must be on paid plans appropriate for production before live records are loaded.

## 1. Target architecture

| Component | Production target | Purpose |
|---|---|---|
| Web application | Fly.io app `lashpro-pos` | Django + Gunicorn |
| Database | Fly Managed Postgres, or an equivalent paid managed PostgreSQL service | Durable transactional data, automated backups, recovery |
| Uploaded images | Cloudinary or another durable object-storage provider | Product/service images shared across machines |
| Static assets | WhiteNoise manifest storage in the container image | Versioned CSS, JavaScript and static images |
| Email | Authenticated SMTP provider | Staff password recovery and transactional email |
| DNS/TLS | Customer-owned domain with Fly certificates | Branded HTTPS access |

The repository currently sets `primary_region = "ams"` in `fly.toml`. Do not move the application to another region until the live database region is confirmed and the application and database can be moved together. For a Kenya-focused deployment, Fly's Johannesburg (`jnb`) region is the nearest Fly region in Africa; it is the preferred target for a new installation **only when the PostgreSQL database is also provisioned in the same region**. The available region list can change; verify it using `fly platform regions`.

Fly's Managed Postgres provides automated backups, recovery/PITR, high availability with failover, monitoring and encryption. Prefer it for a new installation if its current plan and region meet the business requirements. An existing paid Neon or other managed PostgreSQL database may be retained; verify its region, TLS, backup retention, point-in-time recovery and restore process before production use. Do not move an existing database merely to follow this recommendation—plan and rehearse the data migration first.

Useful provider references:
- [Fly.io Managed Postgres](https://fly.io/docs/mpg/)
- [Fly.io regions and platform status](https://fly.io/docs/reference/regions/)
- [Fly.io pricing](https://fly.io/docs/about/pricing/)
- [Fly.io custom domains and TLS](https://fly.io/docs/networking/custom-domain/)

## 2. What the repository does during deployment

- `.python-version` pins Python 3.14.8. The Docker image uses the same Python patch version.
- `Dockerfile` installs the pinned dependencies, collects static assets, and runs Gunicorn as a non-root user.
- `fly.toml` defines the app name, region, HTTPS routing, health check, machine resources and the release command.
- `release.sh` runs `manage.py check --deploy`, applies migrations, and optionally creates the first owner account. The deploy is stopped if the release command fails.
- `DATABASE_URL` is the runtime PostgreSQL connection. Fly Managed Postgres can set it when attached to the app.
- `DATABASE_URL_DIRECT` is optional. Use it only when the database provider supplies a direct/unpooled connection intended for schema migrations.
- `CLOUDINARY_URL` configures durable product/service image uploads. Production mode now refuses to start without Cloudinary or the configured S3-compatible storage backend because Fly Machine filesystems are not a durable media store.
- The app uses database-backed sessions and transaction records. Do not rely on a Machine's local filesystem for customer uploads or business data.

## 3. Pre-deployment decisions and safeguards

Complete these before the first live deployment:

1. **Identify the current data source.** Confirm whether the existing Fly app or another environment already contains real customers, sales, payment records, stock movements, appointments, or staff accounts.
2. **Do not attach an empty database to an app containing live data.** If the production database must change, take a backup, restore it into the target provider, verify row counts and financial totals, test the restored database, and schedule a controlled cutover. Keep the old database intact until acceptance.
3. **Confirm the database region.** Keep Fly Machines close to PostgreSQL. For a new Kenya-focused environment, consider `jnb` for both. The current checked-in app region remains `ams` until this is confirmed.
4. **Choose an owner for infrastructure and billing.** The business must own or explicitly approve the Fly, database, Cloudinary, domain/DNS and email-provider accounts.
5. **Choose production support contacts.** At least one person must receive service alerts and one person must be authorised to restore the database.
6. **Use independent owner/manager accounts.** At least two distinct people must be able to approve refunds and cash variances; do not share the deployment bootstrap account.
7. **Keep synthetic seeding disabled.** `SYNTHETIC_DATA_ENABLED=false` must remain set on the production app.

## 4. Configure Fly application secrets

Authenticate with the Fly account that owns the app:

```bash
fly auth login
fly status --app lashpro-pos
```

Set secrets in the Fly app. Do not commit real values to GitHub, place them in `.env.production.example`, or paste them into support tickets.

Required for the production application:

| Secret / variable | Requirement |
|---|---|
| `DJANGO_SECRET_KEY` | Unique, cryptographically random secret. Keep it stable and securely backed up; integration credentials are encrypted using it. |
| `DATABASE_URL` | Set by `fly mpg attach` for Fly Managed Postgres, or set to the paid managed PostgreSQL connection string. Require TLS for an external database. |
| `CLOUDINARY_URL` | Full Cloudinary URL for the POS app's image uploads, unless the S3-compatible backend is fully configured instead. |
| `EMAIL_HOST` | Authenticated SMTP host. |
| `EMAIL_PORT` | Normally `587` for STARTTLS; use the provider's documented port. |
| `EMAIL_HOST_USER` | SMTP username. |
| `EMAIL_HOST_PASSWORD` | SMTP password/app password. |
| `EMAIL_USE_TLS` | `true` when required by the SMTP provider. |
| `DEFAULT_FROM_EMAIL` | Verified sender address. |

Optional:
- `DATABASE_URL_DIRECT`: direct/unpooled database URL for migrations, if supplied by the provider.
- `EMAIL_TIMEOUT`: SMTP timeout in seconds; default is 10.
- `DJANGO_BOOTSTRAP_OWNER_USERNAME`, `DJANGO_BOOTSTRAP_OWNER_EMAIL`, and `DJANGO_BOOTSTRAP_OWNER_PASSWORD`: use only for the first owner account, then remove all three secrets after confirming login.
- `SYNTHETIC_DATA_ENABLED`: must stay `false` in production.

Example command shape (replace every placeholder locally; never commit the command with real values):

```bash
fly secrets set \
  DJANGO_SECRET_KEY='GENERATE_A_UNIQUE_SECRET' \
  CLOUDINARY_URL='cloudinary://API_KEY:API_SECRET@CLOUD_NAME' \
  EMAIL_HOST='smtp.example.com' \
  EMAIL_PORT='587' \
  EMAIL_HOST_USER='smtp-user' \
  EMAIL_HOST_PASSWORD='SMTP_APP_PASSWORD' \
  EMAIL_USE_TLS='true' \
  DEFAULT_FROM_EMAIL='LashPro <no-reply@example.com>' \
  SYNTHETIC_DATA_ENABLED='false' \
  --app lashpro-pos
```

For a new Fly Managed Postgres database, create the cluster in the same region as the app and attach it to `lashpro-pos` using the current Fly CLI instructions. Attachment normally provisions `DATABASE_URL` as an app secret. For an existing paid external provider, set `DATABASE_URL` yourself. Confirm that the connection works before deploying. Do not echo secrets into terminal logs or GitHub Actions logs.

## 5. Database provisioning, backups and migration safety

### New installation

- Provision a paid managed PostgreSQL cluster with automated backups, point-in-time recovery and a tested restore path.
- Place it in the same region as the Fly application.
- Attach it to the app or configure `DATABASE_URL`.
- Confirm TLS is enabled and the database allows connections from the Fly app.
- Keep a separate encrypted backup outside the database provider's account for business continuity.

### Existing installation or database migration

- Record the source database provider, database name, region, PostgreSQL version and current schema migration.
- Take a fresh backup and restore it into a separate target database.
- Compare row counts and totals for sales, payments, payment allocations, refunds, cash sessions, inventory movements, commission ledgers and audit events.
- Test logins, reports, checkout and reconciliation on the restored copy.
- Schedule a cutover window. Stop writes or use a provider-supported migration/replication process to capture the final changes.
- Keep the original database untouched until the owner signs off the new environment.

### Backup and recovery standard

- Verify automatic backups are enabled and confirm their retention and recovery window in the provider console.
- Make an additional encrypted off-provider backup on a documented schedule.
- Perform a restore rehearsal to a **new, separate database** before live use and at regular intervals thereafter.
- Record the recovery point objective (maximum acceptable data loss) and recovery time objective (maximum acceptable outage) with the business owner.
- Keep the database secret and encryption key backups under separate access controls.
- Never test restoration over the live production database.

For Fly Managed Postgres, the provider documents a rolling ten-day backup window and restore to a new cluster; verify the actual cluster's recovery window and restore behaviour in the dashboard before relying on it. For an external provider, use that provider's documented paid-plan backup and restore controls.

## 6. Durable media storage

The catalogue has `ImageField` fields for products and services. A Fly Machine's local disk is not a durable shared image store.

The POS app needs `CLOUDINARY_URL` (or a fully configured S3-compatible storage backend) to upload images. The storefront, when deployed as a separate app, needs the matching public Cloudinary cloud name to render those images; it must not receive the POS API secret.

After configuration:
1. Upload a test product image from the POS admin.
2. Confirm the stored URL is served by the external media provider.
3. Open the customer storefront and verify the same image loads.
4. Restart or replace the app Machine and verify the image remains available.

See [FLY_MEDIA_STORAGE.md](FLY_MEDIA_STORAGE.md) for the Cloudinary configuration details.

## 7. Deploy the application

Before deploying, confirm that the app secrets are present, the database is reachable, media storage is configured, and the production data source is correct.

```bash
fly deploy --app lashpro-pos
```

Fly executes `release.sh` as the configured release command before the new version receives traffic. The release command:
- runs Django's production deployment checks;
- applies the checked-in migrations;
- bootstraps the owner only when the three bootstrap secrets are present;
- runs synthetic seeding only when explicitly enabled.

A failed release command must be treated as a failed deployment. Do not bypass a failed migration or deployment check to force a release. Inspect `fly logs --app lashpro-pos`, fix the cause, and retry after taking any required backup.

Once the first owner login is confirmed:
- remove `DJANGO_BOOTSTRAP_OWNER_USERNAME`;
- remove `DJANGO_BOOTSTRAP_OWNER_EMAIL`;
- remove `DJANGO_BOOTSTRAP_OWNER_PASSWORD`;
- confirm `SYNTHETIC_DATA_ENABLED=false`.

## 8. Domain and TLS

The current app has the Fly hostname `lashpro-pos.fly.dev`. For a branded POS hostname:

1. Choose and register a domain/subdomain controlled by the business (for example, a dedicated POS subdomain).
2. Add that hostname to `ALLOWED_HOSTS`.
3. Add its full HTTPS origin to `CSRF_TRUSTED_ORIGINS`.
4. Add the hostname to `POS_HOSTS` if its root path should open the staff POS.
5. Set `POS_BASE_URL` to the canonical HTTPS POS origin; the appointment/payment callback URLs use this value.
6. Add the certificate using `fly certs add` and publish exactly the DNS records Fly displays.
7. Verify certificate issuance and renewal using the Fly dashboard/CLI, then test HTTP-to-HTTPS redirection and the application login.
8. Keep `SECURE_HSTS_INCLUDE_SUBDOMAINS=false` and `SECURE_HSTS_PRELOAD=false` until every affected subdomain is HTTPS-only and the business deliberately approves the domain-wide commitment.

The Fly edge terminates TLS and forwards requests to the Machine. `TRUST_PROXY_SSL_HEADER=true` is configured for the Fly proxy; do not enable it on another host unless that proxy overwrites the forwarded-protocol header on every request.

## 9. Availability, machine sizing and monitoring

The current machine definition is one shared CPU with 1 GB RAM. That is a starting size, not a measured capacity guarantee.

For a production service:
- provision at least two application Machines in the chosen primary region if the business requires the app to survive one Machine failure;
- keep the minimum running machine count aligned with the number of Machines actually provisioned;
- confirm both Machines pass the configured `/accounts/login/` health check;
- monitor CPU, memory, restarts, request errors, response latency and database connections;
- configure alerts to a named support contact;
- retain application logs and investigate repeated errors;
- verify that media is external and sessions/data are stored in shared durable services before scaling horizontally.

Useful operational commands:

```bash
fly status --app lashpro-pos
fly checks list --app lashpro-pos
fly logs --app lashpro-pos
fly machines list --app lashpro-pos
fly secrets list --app lashpro-pos
```

The `secrets list` command shows secret names and deployment status, not secret values. Do not share screenshots of secret values from the Fly dashboard.

## 10. Production smoke test

After deployment, use separate named staff accounts and test with controlled transactions:

- HTTPS login, logout and session expiry;
- static CSS and JavaScript load without 404s;
- upload and retrieve a product/service image;
- create a test product and service;
- open and close a cash session;
- complete a product + service checkout;
- print the receipt;
- record a cash payment and a manual M-Pesa reference;
- verify the manual M-Pesa payment remains unverified until reconciliation;
- test a partial payment and repeat submission to confirm idempotency;
- test refund request and independent manager approval;
- verify stock movements, service consumables and commission ledger entries;
- confirm daily reports reconcile to the test sales and payment records;
- verify password recovery email delivery;
- check logs and Fly health checks after the tests.

Use synthetic data on a disposable database for this smoke test. Never run the synthetic seed command against the live business database.

## 11. Render test environment is not production

`render.yaml`, `build.sh` and `Procfile` remain in the repository for the disposable Render synthetic-data path. That Render Free configuration must not be used for real salon operations. Do not copy its free-tier instructions into a production handover. The production target is the Fly.io application defined by `fly.toml`.

## 12. Release gate

Do not declare production ready until all of the following are evidenced:

- [ ] Paid Fly hosting and paid managed PostgreSQL are active.
- [ ] App and database are in a reviewed, low-latency region arrangement.
- [ ] Production secrets are configured in Fly and no real secret is committed.
- [ ] Production storage for product/service uploads is configured and tested.
- [ ] SMTP password recovery is tested.
- [ ] HTTPS, domain, host validation and CSRF settings are verified.
- [ ] Django `check --deploy` passes on the actual Fly environment.
- [ ] Migrations deploy successfully against the intended database.
- [ ] At least two named owner/manager accounts exist.
- [ ] Backups, off-provider copies and a restore rehearsal are complete.
- [ ] Monitoring, alerting and operational ownership are documented.
- [ ] The production smoke test passes and the business owner accepts the release.
