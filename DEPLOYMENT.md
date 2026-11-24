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

The repository currently sets `primary_region = "ams"` in both Fly app configs. Confirm the actual Neon project region and compare it with the Fly app region; the two settings are independent. Keep the database region as close to the application Machines as practical to reduce round-trip latency. Region choice affects performance, not whether the apps share data.

**Neon is the selected production PostgreSQL provider.** Do not provision or attach a separate Fly Managed Postgres database for either production app. Both apps must use the same Neon project, production branch and database. Confirm Neon TLS, compute availability, connection limits, branch retention and restore controls in the Neon console. Do not point one app at a development/staging branch.

Before production writes, verify the Neon backup/PITR history window configured for the project and rehearse restoring to a separate branch. Neon supports branching from a previous point in time, but the usable history window depends on the project configuration/plan; do not assume a particular retention period. Keep an encrypted off-provider export as an additional recovery path.

Useful provider references:
- [Neon connection and pooling guidance](https://neon.com/docs/connect/connection-pooling)
- [Neon branching and recovery guidance](https://neon.com/blog/practical-guide-to-database-branching)
- [Fly.io custom domains and TLS](https://fly.io/docs/networking/custom-domain/)

## 2. What the repository does during deployment

- `.python-version` selects Python 3.13. The Docker image uses the same Python minor version.
- `Dockerfile` installs the pinned dependencies, collects static assets, and runs Gunicorn as a non-root user.
- `fly.toml` defines the staff POS app and runs `release.sh`; `fly.storefront.toml` defines the customer storefront app and deliberately has no release command. The POS app is the sole production schema-migration runner.
- Both apps must connect to the same Neon project, the same Neon branch and the same PostgreSQL database. Neon branches are isolated data environments; connecting one app to a staging/development branch and the other to production creates two separate data states even when both URLs belong to the same Neon project. See [Neon branching guidance](https://neon.com/blog/practical-guide-to-database-branching).
- Configure the same Neon pooled `DATABASE_URL` on both Fly apps, including the same database name and branch endpoint; the pooled hostname commonly includes `-pooler`. Keep `DB_CONN_MAX_AGE=0` and `DB_DISABLE_SERVER_SIDE_CURSORS=true` for the Neon pooled runtime.
- If Neon supplies a direct/unpooled URL for migrations, set `DATABASE_URL_DIRECT` only on the POS app and ensure it targets that exact same Neon branch and database. The release script uses it only for the POS migration process; application runtime continues to use the pooled `DATABASE_URL`.
- The production GitHub workflow deploys POS first and storefront second. Only the POS release applies migrations; the storefront is deployed after the schema is ready. Do not run independent/manual migration commands against production while a release is in progress.
- Pushes to `main` and pull requests run CI; they do not release production. A production release requires a separate `workflow_dispatch` from `main` with `deploy_production=true`, after the backup, infrastructure and business release gates are approved. Both app-scoped Fly tokens must be configured.
- GitHub Actions serializes workflow runs for the same ref. Manual Fly releases are outside that queue and must be coordinated with the workflow and every operator. Protect `main` in GitHub settings: require a pull request and the successful `Django CI / test` check, and disallow ordinary direct pushes.
- `DATABASE_URL` is required in production and must use PostgreSQL TLS. Both apps must be configured with the same Neon pooled connection target: same Neon project, branch and database. Keep the connection URL in Fly secrets only; never put it in Git, build logs, tickets or chat.
- `DATABASE_URL_DIRECT` is optional and is reserved for the POS release migration command when Neon provides a direct/unpooled endpoint. It must refer to the same Neon branch and database as the runtime URL. Do not configure the storefront to run migrations separately. Never expose either URL or its password.
- On Neon, a pooler endpoint and a direct endpoint can have different hostnames and server addresses while reaching the same branch/database. Do not treat matching IP addresses as definitive proof. The cross-app disposable marker test below is the acceptance test for shared-database visibility.
- Prefer a least-privileged runtime role for the shared app traffic. The storefront needs DML privileges for catalogue reads, customer orders and reservations, but it does not need schema ownership. Keep the DDL/migration role in the POS-only `DATABASE_URL_DIRECT` secret and test permissions on a non-production branch before changing production grants.
- Production settings reject a missing `DATABASE_URL`, PostgreSQL TLS modes weaker than `require`, non-zero connection age, or server-side cursors enabled. These settings protect the production connection from silently falling back to legacy DB_* values or unsafe pooled-connection behaviour.
- `CLOUDINARY_URL` configures POS product/service image uploads. The storefront needs the corresponding public Cloudinary name or matching S3-compatible media settings; never give the storefront a POS-only storage secret. Production mode refuses to start without durable media storage.
- The app uses database-backed sessions and transaction records. Do not rely on a Machine's local filesystem for customer uploads or business data.

### Controlled production release

After the approved commit is on `main` and its CI run is successful:

1. Open **GitHub → Actions → Django CI → Run workflow** and select the `main` branch.
2. Leave `deploy_production` false for a CI-only run. Set it to true only for an approved production release.
3. Confirm the workflow deploys `lashpro-pos` first and `lashpro-storefront` second.
4. Record the exact commit SHA and successful Fly release for each app.

Do not configure both production Fly tokens merely to make the CI run green. The tokens enable the explicitly requested production dispatch; they do not prove database, domain, backup or business readiness.

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

Use this query as a read-only diagnostic, not as the final proof. With Neon, a pooled endpoint and a direct endpoint may report different hosts or backend addresses. Confirm in Neon that both Fly app secrets resolve to the same project, branch and database, then run the disposable cross-app marker test below. If the probe fails, treat it as a **stop**; do not run a production release or switch either app to another branch until the configuration is corrected.

### Prove cross-app visibility with a disposable database probe

After the reviewed code and its migration are installed on **both** apps, run the following in order:

```bash
# 1. Create a one-time marker in the POS app's connected database.
fly ssh console --app lashpro-pos -C "python manage.py shared_database_probe create"

# 2. Copy the token from the JSON output and verify it from the storefront app.
fly ssh console --app lashpro-storefront -C "python manage.py shared_database_probe verify --token <TOKEN_FROM_STEP_1>"
```

A successful second command returns `"status": "verified"`, `"shared_record_visible": true` and `"probe_consumed": true`. The one-time row is deleted automatically after successful verification. Its token becomes invalid after 30 minutes; any expired row is removed the next time the create action is run. If verification fails, the apps do not share the same database; stop and reconcile the data sources before any live booking, order, stock or payment activity. Repeat the probe after any secret, Neon branch, endpoint or database change.

The command reports the configured database host/name and the PostgreSQL server reached, but never prints credentials. Keep its output as handover evidence; do not copy connection strings or secret values into GitHub issues, logs or chat.

Record the database host/provider, app and database regions, database name, machine count and which secret names are present. The probe is an explicit disposable write/read/delete check; the initial SQL query above is read-only.

## 5. Configure Fly application secrets

Authenticate with the Fly account that owns the app:

```bash
fly auth login
fly status --app lashpro-pos
```

Set secrets in the Fly app. Do not commit real values to GitHub, place them in `.env.production.example`, or paste them into support tickets.

Set the application secrets on both Fly apps. The database settings must target the same Neon project, branch and PostgreSQL database. Keep each app's Django key stable; do not copy a secret into a repository file.

| Secret / variable | Requirement |
|---|---|
| `DJANGO_SECRET_KEY` | Unique, cryptographically random secret. Keep it stable and securely backed up; integration credentials are encrypted using it. |
| `DATABASE_URL` | Same Neon pooled PostgreSQL URL on both apps, for the same project, branch and database; require `sslmode=require`. |
| `CLOUDINARY_URL` | Full Cloudinary URL on the POS app for image uploads, unless S3-compatible storage is fully configured instead. The storefront only needs the public media name/settings. |
| `EMAIL_HOST` | Authenticated SMTP host. |
| `EMAIL_PORT` | Normally `587` for STARTTLS; use the provider's documented port. |
| `EMAIL_HOST_USER` | SMTP username. |
| `EMAIL_HOST_PASSWORD` | SMTP password/app password. |
| `EMAIL_USE_TLS` | `true` when required by the SMTP provider. |
| `DEFAULT_FROM_EMAIL` | Verified sender address. |

Optional:
- `DATABASE_URL_DIRECT`: optional direct/unpooled Neon URL for POS migrations only. It must point to the same Neon project, branch and database as the runtime URL.
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

For Neon, select one production branch and database. Set the same pooled `DATABASE_URL` in both Fly apps and confirm the project/branch/database in the Neon console. If using `DATABASE_URL_DIRECT`, set it only on the POS app and use the direct endpoint for the same Neon branch. Do not create a second database or use a separate development branch for the storefront. Confirm shared visibility with the disposable marker test before live operations. Do not echo secrets into terminal logs or GitHub Actions logs.

## 6. Database provisioning, backups and migration safety

### New installation

- Provision one Neon project and choose one production branch and database for both apps.
- Choose a Neon region close to the Fly application region where available.
- Configure the same pooled `DATABASE_URL` on both Fly apps and require TLS with `sslmode=require`.
- Keep runtime connection age at zero and server-side cursors disabled for PgBouncer pooling.
- Use a dedicated, least-privileged runtime database role for application traffic. Keep schema-owner/migration privileges out of the storefront; use a POS-only direct/unpooled migration credential if needed.
- Verify the configured Neon point-in-time history window, then keep a separate encrypted backup outside Neon for business continuity.

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

For Neon, confirm the actual project's configured history-retention window and restore workflow in the Neon console. Neon can create a new branch from a selected point in the retained history; rehearse this against a separate branch and verify the restored schema and business totals before relying on it for recovery. See [Neon's point-in-time restore guidance](https://neon.com/blog/announcing-point-in-time-restore). Do not assume the default history window is sufficient for the business's recovery objectives.

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

Fly executes `release.sh` for the POS app before its new version receives traffic. The POS release command:
- runs Django's production deployment checks;
- applies the checked-in migrations to the shared Neon branch;
- bootstraps the owner only when the three bootstrap secrets are present;
- runs synthetic seeding only when explicitly enabled.

The storefront has no release command and does not apply migrations. A failed POS release command must be treated as a failed deployment. Do not bypass a failed migration or deployment check to force a release. Inspect the POS release logs, fix the cause, and retry only after taking any required backup. Deploy the storefront only after the POS release succeeds. Never run a second migration process against production concurrently.

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

### Sentry error tracking

The Django app reports unhandled exceptions to Sentry when `SENTRY_DSN` is configured. Create a **Python/Django** project in Sentry and store its DSN as a Fly secret on **both** production apps because they run the same Django code:

```bash
fly secrets set SENTRY_DSN='https://<public-key>@o<org-id>.ingest.sentry.io/<project-id>' SENTRY_ENVIRONMENT='production' SENTRY_TRACES_SAMPLE_RATE='0.0' --app lashpro-pos
fly secrets set SENTRY_DSN='https://<public-key>@o<org-id>.ingest.sentry.io/<project-id>' SENTRY_ENVIRONMENT='production' SENTRY_TRACES_SAMPLE_RATE='0.0' --app lashpro-storefront
```

Keep the DSN out of committed files and logs. Set `SENTRY_RELEASE` to the deployed Git SHA (or another stable release identifier) when release-level grouping is needed. Error events are enabled independently of tracing; `SENTRY_TRACES_SAMPLE_RATE=0.0` disables performance spans, and a value such as `0.05` samples 5% of requests.

The SDK configuration disables user identity, cookies, request headers, request bodies, query-string values and local-variable capture. Full request URLs are removed because some LashPro routes carry one-time receipt/password-reset tokens; HTTP and log breadcrumbs are excluded, and the same request scrubbing applies to performance transactions. Review Sentry's project-level data scrubbing and access controls as an additional safeguard.

After setting the secrets and deploying both apps, send a non-sensitive connectivity check from the POS app:

```bash
fly ssh console --app lashpro-pos -C "python manage.py shell -c \\"import sentry_sdk; sentry_sdk.capture_message('LashPro Sentry connectivity check', level='info')\\""
```

Confirm the message appears in the Sentry project under the `production` environment. A missing `SENTRY_DSN` leaves the SDK disabled; the app continues to write logs to Fly as before.

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
