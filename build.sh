#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py bootstrap_deploy_owner
