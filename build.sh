#!/usr/bin/env bash
# Script de build Render : dépendances, fichiers statiques, migrations.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
