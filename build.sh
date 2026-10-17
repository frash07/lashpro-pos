#!/usr/bin/env bash
set -euo pipefail

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
