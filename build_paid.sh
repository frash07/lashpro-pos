#!/usr/bin/env bash
set -euo pipefail

case "${DJANGO_ENV:-}" in
  staging|production) ;;
  *)
    echo "build_paid.sh requires DJANGO_ENV=staging or production." >&2
    exit 1
    ;;
esac

if [[ "${SYNTHETIC_DATA_ENABLED:-false}" != "false" ]]; then
  echo "Synthetic seeding must remain disabled for paid environments." >&2
  exit 1
fi

python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py collectstatic --noinput
