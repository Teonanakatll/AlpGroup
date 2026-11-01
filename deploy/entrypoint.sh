#!/bin/sh
# Запуск приложения в контейнере: миграции, сбор статики, gunicorn.
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_WORKERS:-3}" \
    --access-logfile -
