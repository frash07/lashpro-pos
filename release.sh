#!/usr/bin/env bash
set -euo pipefail

# Use Neon’s direct (unpooled) URL for schema changes when supplied.
# The application Machines continue using DATABASE_URL (normally pooled).
if [[ -n "${DATABASE_URL_DIRECT:-}" ]]; then
  export DATABASE_URL="$DATABASE_URL_DIRECT"
fi

python manage.py check --deploy
python manage.py migrate --noinput
python manage.py bootstrap_deploy_owner

# Synthetic records are opt-in and the management command checks the target DB.
if [[ "${SYNTHETIC_DATA_ENABLED:-false}" == "true" ]]; then
  python manage.py seed_synthetic_data
fi
