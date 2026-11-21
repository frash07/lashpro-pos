# LashPro POS production deployment — Fly.io

This is the canonical production deployment guide for the LashPro POS and storefront Fly.io applications defined by `fly.toml` and `fly.storefront.toml`.

**Production boundary:** Both Fly apps must use paid hosting and the same approved, paid PostgreSQL database before live customer records, payments, inventory, or business-critical operations are entered.

## 1. Target architecture

| Component | Production target | Purpose |
|---|---|---|
| Web applications | Fly.io apps `lashpro-pos` (staff POS) and `lashpro-storefront` (customer storefront) | Django + Gunicorn from the same repository |
| Database | One paid PostgreSQL database configured for both apps | Shared catalogue, customers, bookings, orders, sales, payments and inventory |
| Uploaded images | Cloudinary or another durable object-storage provider | Product/service images shared across machines |
| Static assets | WhiteNoise manifest storage in the container image | Versioned CSS, JavaScript and static images |
| Email | Authenticated SMTP provider | Staff password recovery and transactional email |
| DNS/TLS | Customer-owned domain with Fly certificates | Branded HTTPS access |

The repository currently sets `primary_region = "ams"` in both Fly app configs. Keep both apps close to the verified database region. **Amsterdam is an actively listed Fly Managed Postgres region**, so it is the lowest-risk same-region choice for this existing setup. Johannesburg (`jnb`) is a Fly Machines region, but it is **not** in Fly's currently published Managed Postgres region list; do not provision Fly Managed Postgres in `jnb` or move the apps there as part of this database setup. The managed-database region list can change; verify it at provisioning time.

Fly Managed Postgres provides automated backups and point-in-time recovery, high availability with automatic failover, monitoring and encryption. Its current published Basic plan is US$38/month plus storage at US$0.28 per provisioned GB/month; the published starting storage is 10 GB, so budget from approximately US$40.80/month before tax, egress or any app compute charges. The next published Starter plan is US$72/month plus storage. Confirm current pricing and availability in the Fly dashboard before provisioning. For this single-salon alpha, start with Basic and upgrade if measured CPU, memory, storage or connection demand requires it.

An existing paid Neon or other managed PostgreSQL database may be retained instead. Verify its region, TLS, plan, backup retention, point-in-time recovery and restore process before production use. Do not replace or attach a new empty database until the current `DATABASE_URL` target and whether it contains business data are verified. Rehearse a complete dump/restore and financial-record reconciliation before cutover.

Useful provider references:
- [Fly.io Managed Postgres](https://fly.io/docs/mpg/)
- [Fly.io regions and platform status](https://fly.io/docs/reference/regions/)
- [Fly.io pricing](https://fly.io/docs/about/pricing/)
- [Fly.io custom domains and TLS](https://fly.io/docs/networking/custom-domain/)

## 2. What the repository does during deployment

- `.python-version` selects Python 3.13. The Docker image uses the same Python minor version.
- `Dockerfile` installs the pinned dependencies, collects static assets, and runs Gunicorn as a non-root user.
- `fly.toml` defines the staff POS app; `fly.storefront.toml` defines the customer storefront app. Each sets its hostnames, HTTPS routing, health check, machine resources and release command.
- Both apps must point to the same intended PostgreSQL database. Compare provider, host and database name safely; never assume separate app secrets already match.
- Both app configs run `release.sh`, which checks deployment settings, applies migrations and optionally bootstraps the first owner. The production GitHub workflow deploys POS first and storefront second so these migration commands cannot race. Keep deployments serialized if they are run manually.
- GitHub Actions serializes workflow runs for each branch, so two `main` production runs cannot overlap their release commands. Any manual Fly deployment must still be coordinated with the workflow and with other operators.
- `DATABASE_URL` is the runtime PostgreSQL connection for both apps. If the apps use separate credentials, verify that they still resolve to the same database host and database name.
- `DATABASE_URL_DIRECT` is optional but recommended when the provider supplies a direct/unpooled connection for schema migrations. For Fly Managed Postgres, copy the Direct connection URL from the cluster's Connect tab into the Fly app secret `DATABASE_URL_DIRECT`. The release script temporarily uses it for migrations while web Machines use the pooled `DATABASE_URL` provided by `fly mpg attach`. Do not copy a password into Git or ChatGPT.
- `CLOUDINARY_URL` configures POS product/service image uploads. The storefront needs the corresponding public Cloudinary name or matching S3-compatible media settings; never give the storefront a POS-only storage secret. Production mode refuses to start without durable media storage.
- The app uses database-backed sessions and transaction records. Do not rely on a Machine's local filesystem for customer uploads or business data.

## 3. Pre-deployment decisions and safeguards

Complete these before the first live deployment:

1. **Identify the current data source.** Confirm whether the existing Fly app or another environment already contains real customers, sales, payment records, stock movements, appointments, or staff accounts.
2. **Do not attach an empty database to an app containing live data.** If the production database must change, take a backup, restore it into the target provider, verify row counts and financial totals, test the restored database, and schedule a controlled cutover. Keep the old database intact until acceptance.
3. **Confirm the database region.** Keep Fly Machines close to PostgreSQL. For a new Kenya-focused environment, consider `jnb` for both. The current checked-in app region remains `ams` until this is confirmed.
4. **Choose an owner for infrastructure and billing.** The business must own or explicitly approve the Fly, database, Cloudinary, domain/DNS and email-provider accounts.
5. **Choose production support contacts.** At least one person must receive service alerts and one person must be authorised to restore the database.
6. **Use independent owner/manager accounts.** At least two distinct people must be able to approve refunds and cash variances; do not share the deployment bootstrap account.
7. **Keep synthetic seeding disabled.** `SYNTHETIC_DATA_ENABLED=false` must remain set on both production apps.

## 4. Inspect the existing app before changing database secrets

Run these read-only commands from a machine authenticated to the Fly organization:

```bash
fly status --app lashpro-pos
fly scale show --app lashpro-pos
fly machines list --app lashpro-pos
fly secrets list --app lashpro-pos
fly mpg list
```

`fly secrets list` displays secret names, not values. Do not use `fly secrets show` or print the raw `DATABASE_URL` into a shared terminal/chat transcript.

Run this read-only query once inside **each** app. It reports the configured host/database and the database server actually reached, without displaying a username, password or full connection URL:

```bash
fly ssh console --app lashpro-pos -C "python manage.py shell -c 'from django.db import connection; c=connection.cursor(); c.execute(\\"SELECT current_database(), inet_server_addr()::text, inet_server_port()\\"); row=c.fetchone(); d=connection.settings_dict; print(\\"DATABASE_HOST=\\"+str(d.get(\\"HOST\\"))); print(\\"DATABASE_PORT=\\"+str(d.get(\\"PORT\\"))); print(\\"CONFIGURED_DATABASE=\\"+str(d.get(\\"NAME\\"))); print(\\"CONNECTED_DATABASE=\\"+str(row[0])); print(\\"DATABASE_SERVER=\\"+str(row[1])+\\":\\"+str(row[2]))'"
fly ssh console --app lashpro-storefront -C "python manage.py shell -c 'from django.db import connection; c=connection.cursor(); c.execute(\\"SELECT current_database(), inet_server_addr()::text, inet_server_port()\\"); row=c.fetchone(); d=connection.settings_dict; print(\\"DATABASE_HOST=\\"+str(d.get(\\"HOST\\"))); print(\\"DATABASE_PORT=\\"+str(d.get(\\"PORT\\"))); print(\\"CONFIGURED_DATABASE=\\"+str(d.get(\\"NAME\\"))); print(\\"CONNECTED_DATABASE=\\"+str(row[0])); print(\\"DATABASE_SERVER=\\"+str(row[1])+\\":\\"+str(row[2]))'"
```

The host/provider, port, configured database and connected database must agree with the intended production target. Treat any mismatch as a **stop**; do not attach a new database or run a release until the existing data source is understood. This is a read-only inventory.

### Prove cross-app visibility with a disposable database probe

After the reviewed code and its migration are installed on **both** apps, run the following in order:

```bash
# 1. Create a one-time marker in the POS app's connected database.
fly ssh console --app lashpro-pos -C "python manage.py shared_database_probe create"

# 2. Copy the token from the JSON output and verify it from the storefront app.
fly ssh console --app lashpro-storefront -C "python manage.py shared_database_probe verify --token <TOKEN_FROM_STEP_1>"
```

A successful second command returns `"status": "verified"`, `"shared_record_visible": true` and `"probe_consumed": true`. The one-time row is deleted automatically after successful verification. Its token becomes invalid after 30 minutes; any expired row is removed the next time the create action is run. If verification fails, the apps do not share the same database; stop and reconcile the data sources before any live booking, order, stock or payment activity.

The command reports the configured database host/name and the PostgreSQL server reached, but never prints credentials. Keep its output as handover evidence; do not copy connection strings or secret values into GitHub issues, logs or chat.

Record the database host/provider, app and database regions, database name, machine count and which secret names are present. The probe is an explicit disposable write/read/delete check; the initial SQL query above is read-only.

## 5. Configure Fly application secrets

Authenticate with the Fly account that owns the app:

```bash
fly auth login
fly status --app lashpro-pos
```

Set secrets in the Fly app. Do not commit real values to GitHub, place them in `.env.production.example`, or paste them into support tickets.

Set the application secrets on both Fly apps. The database settings must target the same database. Keep each app's Django key stable; do not copy a secret into a repository file.

| Secret / variable | Requirement |
|---|---|
| `DJANGO_SECRET_KEY` | Unique, cryptographically random secret. Keep it stable and securely backed up; integration credentials are encrypted using it. |
| `DATABASE_URL` | Set by `fly mpg attach` for Fly Managed Postgres, or set to the paid managed PostgreSQL connection string. Require TLS for an external database. |
| `CLOUDINARY_URL` | Full Cloudinary URL on the POS app for image uploads, unless S3-compatible storage is fully configured instead. The storefront only needs the public media name/settings. |
| `EMAIL_HOST` | Authenticated SMTP host. |
| `EMAIL_PORT` | Normally `587` for STARTTLS; use the provider's documented port. |
| `EMAIL_HOST_USER` | SMTP username. |
| `EMAIL_HOST_PASSWORD` | SMTP password/app password. |
| `EMAIL_USE_TLS` | `true` when required by the SMTP provider. |
| `DEFAULT_FROM_EMAIL` | Verified sender address. |

Optional:
- `DATABASE_URL_DIRECT`: direct/unpooled database URL for migrations, if supplied by the provider. For Fly Managed Postgres, use the Direct URL shown in the cluster Connect tab.
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

For a new Fly Managed Postgres database, create the cluster in the same region as both apps. Configure both app secrets to use the same database host and database name; do not create a second database for the storefront. For an existing paid external provider, set `DATABASE_URL` on both apps. Confirm the connection safely before deploying. Do not echo secrets into terminal logs or GitHub Actions logs.

## 6. Database provisioning, backups and migration safety

### New installation

- Provision a paid managed PostgreSQL cluster with automated backups, point-in-time recovery and a tested restore path.
- Place it in the same region as both Fly applications.
- Configure `DATABASE_URL` on both apps to the same database.
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

## 7. Durable media storage

The catalogue has `ImageField` fields for products and services. A Fly Machine's local disk is not a durable shared image store.

The POS app needs `CLOUDINARY_URL` (or a fully configured S3-compatible storage backend) to upload images. The storefront, when deployed as a separate app, needs the matching public Cloudinary cloud name to render those images; it must not receive the POS API secret.

After configuration:
1. Upload a test product image from the POS admin.
2. Confirm the stored URL is served by the external media provider.
3. Open the customer storefront and verify the same image loads.
4. Restart or replace the app Machine and verify the image remains available.

See [FLY_MEDIA_STORAGE.md](FLY_MEDIA_STORAGE.md) for the Cloudinary configuration details.

## 8. Deploy the application

Before deploying, confirm that the app secrets are present, the database is reachable, media storage is configured, and the production data source is correct.

Deploy the POS first, then the storefront. The shared schema migration is applied from the POS release command; the storefront release follows only after POS deploy succeeds. Do not run these deploys concurrently.

```bash
fly deploy --config fly.toml --app lashpro-pos --remote-only
fly deploy --config fly.storefront.toml --app lashpro-storefront --remote-only
```

Fly executes `release.sh` for each app before the new version receives traffic. The release command:
- runs Django's production deployment checks;
- applies the checked-in migrations;
- bootstraps the owner only when the three bootstrap secrets are present;
- runs synthetic seeding only when explicitly enabled.

A failed release command must be treated as a failed deployment. Do not bypass a failed migration or deployment check to force a release. Inspect the logs for both apps, fix the cause, and retry only after taking any required backup. Since both apps use one database, allow only one release command to run at a time.

Once the first owner login is confirmed:
- remove `DJANGO_BOOTSTRAP_OWNER_USERNAME`;
- remove `DJANGO_BOOTSTRAP_OWNER_EMAIL`;
- remove `DJANGO_BOOTSTRAP_OWNER_PASSWORD`;
- confirm `SYNTHETIC_DATA_ENABLED=false`.

## 9. Domain and TLS

The current apps have the Fly hostnames `lashpro-pos.fly.dev` and `lashpro-storefront.fly.dev`. For the branded hosts:

1. Point `domain.ke` to `lashpro-storefront` and `pos.domain.ke` to `lashpro-pos`.
2. Add each hostname to the corresponding app's `ALLOWED_HOSTS` and HTTPS origin to its `CSRF_TRUSTED_ORIGINS`.
3. Add `pos.domain.ke` to `POS_HOSTS` and set `POS_BASE_URL=https://pos.domain.ke` on both apps so staff links and callbacks use the canonical POS origin.
4. Add both certificates using `fly certs add` and publish the exact DNS records Fly displays.
5. Verify certificate issuance/renewal, HTTP-to-HTTPS redirects, host validation, cross-app links, and CSRF-protected forms on both domains.
6. Keep `SECURE_HSTS_INCLUDE_SUBDOMAINS=false` and `SECURE_HSTS_PRELOAD=false` until every affected subdomain is HTTPS-only and the business deliberately approves the domain-wide commitment.

The Fly edge terminates TLS and forwards requests to the Machine. `TRUST_PROXY_SSL_HEADER=true` is configured for the Fly proxy; do not enable it on another host unless that proxy overwrites the forwarded-protocol header on every request.

## 10. Availability, machine sizing and monitoring

The current machine definition is one shared CPU with 1 GB RAM. That is a starting size, not a measured capacity guarantee. The POS config keeps two Machines running and the storefront config keeps one; Fly does not create the extra Machines from these settings alone.

For a production service:
- provision at least two POS Machines and the approved number of storefront Machines;
- keep each app's minimum running machine count aligned with the Machines actually provisioned;
- confirm every Machine passes its configured `/accounts/login/` health check;
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

## 11. Production smoke test

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
