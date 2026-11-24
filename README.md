# LashPro POS

Django/PostgreSQL application for LashPro KE's retail, studio and academy operations.

- Storefront: https://lashproke.cc
- Staff POS: https://pos.lashproke.cc
- Fly applications: lashpro-pos and lashpro-storefront; one shared Neon PostgreSQL production database; shared durable product/service media.

## Local development

Use Python 3.13 and a disposable PostgreSQL database. Create a local untracked .env containing DJANGO_SECRET_KEY, DATABASE_URL (local PostgreSQL), DEBUG=true and DJANGO_ENV=development. Never use production credentials locally.

```sh
python -m venv .venv
# Activate the environment using the command appropriate for your shell.
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py test
```

Use named owner, manager, cashier, technician and trainer accounts; never share a superuser. Customer accounts are distinct from staff.

## Release and operation

- [Deployment, backups, recovery and smoke tests](DEPLOYMENT.md)
- [Production configuration reference](.env.production.example)
- [Payment and notification integrations](INTEGRATIONS.md)
- [WhatsApp commerce](WHATSAPP_COMMERCE.md)
- [Online orders](ONLINE_ORDERS.md)
- [Appointments](APPOINTMENTS.md)
- [Public-site abuse and reservation scheduler](PUBLIC_SITE_ABUSE.md)
- [Client handover evidence](docs/CLIENT_HANDOVER.md)
- [Legal and privacy checklist](docs/LEGAL_HANDOVER_CHECKLIST.md)
- [Deferred roadmap](PRODUCT_ROADMAP.md)

CI runs Django tests, migration checks, asset compilation and a Docker build. Production release is an explicit workflow dispatch from main following approval. The POS runs migrations first; the storefront follows. A successful CI run alone is not production acceptance. KRA eTIMS credential storage is not fiscal invoice submission.
