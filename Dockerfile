FROM python:3.14.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /code

# Psycopg's binary wheel is installed from requirements.txt. Keep build tools
# only in the image layer used to install dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev passwd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /code

# Django settings require a secret and DATABASE_URL even during collectstatic.
# These are disposable build-only values; runtime values come from Fly secrets.
RUN DJANGO_SECRET_KEY=build-only-not-a-runtime-secret \
    DATABASE_URL=postgresql://build:build@127.0.0.1:5432/build \
    python manage.py collectstatic --noinput

# Do not run the internet-facing WSGI process as root.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app \
    && chown -R app:app /code

USER app

EXPOSE 8080

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "--access-logfile", "-", "--error-logfile", "-"]
