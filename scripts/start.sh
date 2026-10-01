#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py import_fuel_data data/raw/fuel-prices.csv data/enriched/stations.json
exec python manage.py runserver 0.0.0.0:8000 --noreload
