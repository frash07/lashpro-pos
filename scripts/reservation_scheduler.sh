#!/usr/bin/env bash
set -euo pipefail
if [[ "${DJANGO_ENV:-}" != production ]]; then
  echo "Reservation scheduler requires DJANGO_ENV=production." >&2
  exit 1
fi
trap 'exit 0' TERM INT
while true; do
  python manage.py expire_public_reservations
  sleep 60 &
  wait $!
done
