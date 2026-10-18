# LashPro POS Alpha release runbook

## Scope

This runbook is for a supervised, single-salon Alpha using cashier checkout, product stock tracking, lash services, cash, manual M-Pesa references, service completion and commissions, refunds, cash sessions, and current reports. Manual M-Pesa entries remain unverified until an owner or manager compares them with the statement.

Appointments, automated M-Pesa integration, a PWA, and multi-branch support are outside this Alpha. Tell pilot staff this before their first shift.

## Local stabilization status — 16 October 2026

- Historical local baseline (16 October 2026, before the deployment compatibility pin): using Django 6.1.2, the local PostgreSQL database had pending Alpha migrations applied, system/dependency/migration checks passing, and 53 tests passing. The deployment branch now pins Django 6.0.9 to align with released WhiteNoise 6.12.0 support; rerun the new PostgreSQL CI workflow before treating the 6.0.9 baseline as verified.
- The one legacy pending cash entry was confirmed as a test/abandoned record by the user, cancelled with an immutable approval audit event, and retains its original reference. The current database has no pending payment rows.
- A pre-change PostgreSQL backup was created and restored successfully into a separate temporary database; core migration and payment tables were verified, then the temporary restore database was removed. The backup is on this development machine and is not an off-site production backup.
- The local `check --deploy` still reports six warnings: HSTS is unset, HTTPS redirect is off, the local secret is unsuitable for deployment, secure session and CSRF cookies are off, and `DEBUG=True`. Configure these against the real HTTPS host before Alpha deployment.

## Release blockers to close

- Provision the Alpha host, DNS name, TLS certificate, production PostgreSQL database, and a production WSGI server. The development runserver is not suitable for Alpha.
- Install the real host and proxy values in Render's environment settings (or an untracked private `.env` for local use). Use `.env.production.example` as the reference and never use its placeholder secret. The local development environment is not configured for production deployment.
- Keep Django 6.0.9 and WhiteNoise 6.12.0 pinned together on this deployment branch unless a released WhiteNoise version explicitly supports the intended Django version and the full PostgreSQL CI workflow passes.
- Create at least two distinct owner/manager accounts for independent approvals. A user cannot approve their own refund or cash variance.
- Review any existing PENDING payments in the target Alpha database before migration; the payment migration intentionally stops if any remain. The local development row was user-confirmed as abandoned, cancelled, and audited during stabilization.
- Load and verify the real catalogue, opening stock, service prices, technician accounts, and staff roles. Open a cash session with the correct float before accepting cash.
- Choose who receives deployment errors and who can restore backups. Configure the SMTP variables documented in DEPLOYMENT.md before relying on email password recovery. With SMTP unset, users are directed to a manager rather than having reset links written to logs.

## Configure the Alpha host

1. Use `.env.production.example` as the environment-variable reference and configure the values in the host's secret settings (or create an untracked private `.env` for local use). Replace the secret, database credentials, domain, CSRF origin, SMTP values, and proxy settings. Ensure the proxy overwrites X-Forwarded-Proto; only then set TRUST_PROXY_SSL_HEADER=True.
2. Set ALLOWED_HOSTS to the exact Alpha host and CSRF_TRUSTED_ORIGINS to its HTTPS origin. Keep DEBUG=False, HTTPS redirection on, and secure session/CSRF cookies on.
3. Start with a short HSTS duration. Keep subdomain and preload flags off until every affected hostname is HTTPS-only and the owner deliberately approves the domain-wide commitment.
4. Configure Axes proxy-count/order values only for the real proxy chain. Do not trust a client-provided forwarded-IP header.
5. Run the app behind a production WSGI server and the TLS proxy. Do not expose Django's development server to the internet.

## Pre-deployment checks

Run from the project directory with the Alpha environment loaded:

    .\venv314\Scripts\python.exe manage.py check
    .\venv314\Scripts\python.exe manage.py check --deploy
    .\venv314\Scripts\python.exe manage.py makemigrations --check --dry-run
    .\venv314\Scripts\python.exe -m pip check
    .\venv314\Scripts\python.exe manage.py test
    .\venv314\Scripts\python.exe manage.py collectstatic --noinput

Resolve every deployment warning that applies to the actual host. HSTS include-subdomains/preload warnings may remain while those settings are intentionally disabled; record the decision and do not enable them until the domain is ready.

## Deploy and recovery

1. Take a database backup and confirm it can be read before changing the schema.
2. Deploy the reviewed application version and locked dependencies.
3. Apply migrations with manage.py migrate. The new migration backfills unique payment retry keys and adds database constraints/guards. Do not run makemigrations on the Alpha host.
4. Confirm the HTTPS login page, CSS, cashier checkout, receipt, cash session, reconciliation queue, refunds, commission screen, and reports load.
5. Create staff accounts with individual passwords; do not share cashier logins. Configure a second approver before the first refund or variance approval is needed.
6. Rehearse a database restore to a separate database before the pilot begins. Keep a verified pre-migration backup and a documented rollback decision.

## Supervised pilot shift

Use test entries first, then real low-value transactions only after the smoke checks pass.

- Open a cash session and confirm the opening float.
- Sell a product and a service together; verify the customer, technician, catalogue prices, total, stock deduction, and printed receipt.
- Attempt a discounted checkout as a cashier and confirm it is rejected. Have a manager apply a small discount with a reason and confirm the audit event records the manager and reason.
- Record a manual M-Pesa payment. Confirm it remains unverified, then have a different manager reconcile it against the statement. Confirm reports count it only after confirmation.
- Collect a partial balance payment and repeat the same submission once; confirm there is only one payment record.
- Mark the service complete; confirm consumables and commission are posted once.
- Request a refund as one staff member and approve it as another. Confirm any stock return, payout trail, commission reversal, audit events, and net receipt total.
- Close the cash session. Reconcile expected and counted cash; have another owner/manager review any variance.
- Compare the daily report with the transaction list and cash/M-Pesa statements.

## Alpha exit criteria

Proceed beyond the supervised pilot only when the test suite passes on the deployed database, the deployment check has no unexplained warnings, the backup restore works, all pilot transactions reconcile to the expected totals, and staff can complete the shift without database-admin intervention.
