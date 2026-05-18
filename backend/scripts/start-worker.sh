#!/bin/sh
set -eu

mkdir -p "${MEDIA_ROOT:-/app/media}"

exec celery -A app.worker.celery_app worker \
  --loglevel="${CELERY_LOG_LEVEL:-info}" \
  --queues="${CELERY_QUEUES:-default,blog_generation,image_generation,audit}" \
  --concurrency="${WORKER_CONCURRENCY:-3}"
