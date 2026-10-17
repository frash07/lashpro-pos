# LashPro POS deployment: Render + Neon

This setup creates a public alpha deployment on Render's free web service and uses Neon Free for PostgreSQL. It prepares the app for a supervised trial with synthetic data. Render explicitly says its free web services are not for production applications; do not use this free setup for real customer records, payments, inventory operations, or business-critical sales.

## What the deployment files do

- .python-version pins Render to Python 3.14.8.
- render.yaml describes one free Render web service and asks for database and secret values during initial Blueprint creation.
- build.sh installs requirements, runs Django's production deployment check, collects static files, applies migrations, and optionally creates the first owner.
- Procfile starts Gunicorn with one worker and two threads to fit the free service's limited memory.
- config/settings.py accepts either a DATABASE_URL or the existing local DB_* variables. It adds Render's hostname and HTTPS URL automatically, requires SSL by default for URL-based connections, disables server-side cursors for Neon pooler compatibility, and keeps database connections short-lived.
- accounts/management/commands/bootstrap_deploy_owner.py creates an owner only when all three bootstrap credentials are present. It validates the password and never changes an existing account.

The app currently has no persistent uploaded-file fields, so the free service's ephemeral local disk does not need to hold business media. Do not add persistent user uploads without external object storage.

## Compatibility and automated validation

The alpha pins Django 6.0.9 alongside WhiteNoise 6.12.0. The released WhiteNoise 6.12.0 package metadata lists Django 6.0 support; Django 6.1 support is not listed in that release. Keep these versions together unless a newer released WhiteNoise version explicitly supports the selected Django version and CI passes.

The GitHub Actions workflow in `.github/workflows/ci.yml` provisions PostgreSQL and runs dependency checks, Django system checks, migration-drift checks, fresh migrations, the test suite, and static collection. Treat a failing workflow as a release blocker.

## Create the alpha

1. Push the project to a private GitHub repository that Render can access. Do not include .env, local databases, virtual environments, or staticfiles/.
2. Create a Neon project. Choose a region close to the Render service and, if possible, use the same region for both to reduce database latency.
3. In Neon, copy the pooled connection string (its hostname includes -pooler) and ensure it includes sslmode=require. Keep it private.
4. In Render, create a new Blueprint from the repository containing render.yaml. Choose the same or nearest supported region to Neon.
5. When prompted for the sync: false values, provide:
   - Neon's pooled connection string as DATABASE_URL;
   - a unique DJANGO_SECRET_KEY, generated with Django's get_random_secret_key;
   - a first owner username, email, and strong password for the three DJANGO_BOOTSTRAP_OWNER_* settings.
6. Let the first build finish. It checks the deployment settings, collects static files, migrates the empty Neon database, and creates the owner account. Open the Render URL and sign in.
7. After confirming that owner login works, remove all three DJANGO_BOOTSTRAP_OWNER_* values from Render. The command then skips on later builds. If a later build fails after the owner was created, the rerun detects the same owner and leaves its password unchanged.
8. Keep SYNTHETIC_DATA_ENABLED=false unless deliberately preparing synthetic test records. For the dedicated Alpha test service only, set DJANGO_ENV=synthetic-test, add SYNTHETIC_DATA_CONFIRM_DATABASE equal to the exact database name from the Neon connection URL, set a strong SYNTHETIC_STAFF_PASSWORD, and then set SYNTHETIC_DATA_ENABLED=true. Redeploy once; build.sh runs the guarded seed command after migrations. The command refuses non-PostgreSQL databases and requires the exact database-name confirmation.
9. The seed creates demo users demo_manager, demo_cashier, demo_technician_1, and demo_technician_2; five fictional customers; three products; three services; one consumable rule; and ledgered opening stock. The password supplied is applied only to new demo accounts; reruns do not change existing passwords. It does not create sales or payments, so exercise checkout, reconciliation, refunds, commissions and cash sessions manually.
10. Never enable synthetic seeding against real business data. Keep the test-only environment settings aligned with the values in render.yaml if synchronizing the Blueprint.
11. If you add a custom domain, add its hostname to ALLOWED_HOSTS and its https:// origin to CSRF_TRUSTED_ORIGINS. Keep HTTPS enabled.

Render supplies RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_URL; settings use those for the generated service domain. Do not put secrets in the repository or commit .env.production.example values after replacing its placeholders.

## Free-tier behavior and data limits

Render free web services spin down after 15 minutes without traffic and may take about a minute to start again. Their local filesystem is ephemeral, and free web services do not provide SSH shell access, one-off jobs, or a separate pre-deploy command. This is why this alpha runs migrations in the build command. Test every migration against a disposable Neon database before deploying schema changes.

Neon Free currently includes 1 GB of database storage per project, 100 CU-hours per month, and a six-hour restore window. Limits and plan terms can change. Monitor the Neon dashboard and keep a separate backup before any important data is entered.

These services are suitable for trying the app with synthetic records. Upgrade to a paid hosting/database plan with backups, monitoring, and an operational restore process before using it for actual salon transactions or personal data. The free-tier alpha may be slow after idle, and it is not an availability guarantee.

## Before sharing the URL

- Confirm python manage.py check --deploy is clean in the Render build log.
- Verify login, product/service setup, checkout, cash/manual M-Pesa, receipt, refunds, cash-session close, and reconciliation using synthetic data.
- Keep owner credentials private, remove bootstrap credentials after the first owner login, and create named staff accounts with appropriate roles.
- Keep HSTS at 300 seconds during the alpha. includeSubDomains applies to subdomains below the configured hostname; leave it enabled only if those subdomains all use HTTPS. The preload flag does not submit a host to browser preload lists.
- Take a database backup and verify that you can restore it before moving beyond synthetic trial data.
