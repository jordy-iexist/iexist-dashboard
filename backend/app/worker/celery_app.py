from celery import Celery
from kombu import Queue

from app.core.config import settings

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
    },
)

celery_app.autodiscover_tasks([
    "app.worker",
    "app.features.blogs.worker",
    "app.features.seo_tracker.worker",
    "app.features.seo_meta.worker",
    "app.features.website_audit.worker",
])
