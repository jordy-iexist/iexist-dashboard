#!/bin/sh
set -eu

mkdir -p "${MEDIA_ROOT:-/app/media}"

python -m alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
