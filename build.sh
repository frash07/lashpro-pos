#!/usr/bin/env bash
set -euo pipefail

# This build is intentionally limited to the synthetic Alpha service. Paid
# staging/production services use build_paid.sh and preDeployCommand instead.
if [[ "${DJANGO_ENV:-}" != "synthetic-test" ]]; then
  echo "build.sh is only for the DJANGO_ENV=synthetic-test Alpha service." >&2
  exit 1
fi

python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py bootstrap_deploy_owner

# Never seed by default. This command independently validates the environment,
# database-name confirmation, PostgreSQL backend, and test-only staff password.
if [[ "${SYNTHETIC_DATA_ENABLED:-false}" == "true" ]]; then
  python manage.py seed_synthetic_data
fi
