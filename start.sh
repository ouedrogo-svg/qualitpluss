#!/usr/bin/env bash
# Secours : regénère les statiques à chaque démarrage (disque Render éphémère).
set -eu

python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}"
