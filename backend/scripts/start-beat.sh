#!/bin/sh
set -eu

# Celery beat: plant de periodieke taken in (o.a. de dagelijkse sitemap-monitor).
# Draai precies één instantie, anders gaat elke taak dubbel. Redis bewaart niets
# (geen persistentie), dus het schedule-bestand leeft in de container.
exec celery -A app.worker.celery_app beat \
  --loglevel="${CELERY_LOG_LEVEL:-info}" \
  --schedule=/tmp/celerybeat-schedule
