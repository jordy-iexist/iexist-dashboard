from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings, validate_required_secrets

validate_required_secrets(settings)

celery_app = Celery(
    "worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Amsterdam",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    # Voorkom dat een vastgelopen taak (bv. hangende crawl of API-call) een
    # worker-slot oneindig bezet houdt; soft limit geeft de taak de kans om
    # de jobstatus nog op "failed" te zetten.
    task_soft_time_limit=1500,
    task_time_limit=1800,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.worker_concurrency,
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("blog_generation"),
        Queue("image_generation"),
        Queue("audit"),
    ),
    task_routes={
        "app.worker.tasks.generate_blog_task": {"queue": "blog_generation"},
        "app.worker.tasks.generate_blog_image_task": {"queue": "image_generation"},
        "app.worker.tasks.scan_website_keywords_task": {"queue": "blog_generation"},
        "app.worker.tasks.run_website_meta_optimization_task": {"queue": "blog_generation"},
        "app.worker.tasks.run_website_audit_task": {"queue": "audit"},
        "app.worker.tasks.run_launch_scan_task": {"queue": "audit"},
        "app.worker.tasks.run_geo_scan_task": {"queue": "audit"},
        "app.worker.tasks.run_content_scan_task": {"queue": "audit"},
        "app.worker.tasks.run_content_analysis_task": {"queue": "audit"},
        "app.worker.tasks.run_quarterly_scan_task": {"queue": "audit"},
        "app.worker.tasks.run_golive_scan_task": {"queue": "audit"},
        "app.worker.tasks.run_sitemap_monitor_dispatch_task": {"queue": "audit"},
        "app.worker.tasks.run_sitemap_monitor_task": {"queue": "audit"},
    },
    # Celery beat (service `beat`, precies één instantie). Tijden in `timezone` hierboven.
    beat_schedule={
        # Dagelijkse sitemap-monitor: na de pg_dump van 03:00. De dispatcher kijkt zelf
        # naar SITEMAP_MONITOR_ENABLED (noodrem) en de schakelaar per klant.
        "sitemap-monitor-dagelijks": {
            "task": "app.worker.tasks.run_sitemap_monitor_dispatch_task",
            "schedule": crontab(hour=settings.sitemap_monitor_hour, minute=0),
        },
    },
)

celery_app.autodiscover_tasks([
    "app.worker",
    "app.features.blogs.worker",
    "app.features.seo_tracker.worker",
    "app.features.seo_meta.worker",
    "app.features.website_audit.worker",
    "app.features.launch_checklist.worker",
])
