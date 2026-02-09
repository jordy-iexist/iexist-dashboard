from celery.utils.log import get_task_logger

from app.database import supabase
from app.services.csv_service import fill_template
from app.services.openai_service import generate_blog
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def generate_blog_task(self, job_id: str):
    """Generate a blog for a specific job."""
    try:
        job_result = (
            supabase.table("jobs")
            .select("*, csv_rows(*)")
            .eq("id", job_id)
            .single()
            .execute()
        )
        job = job_result.data
        row_data = job["csv_rows"]["data"]

        row_result = (
            supabase.table("csv_rows")
            .select("*, csv_uploads(*)")
            .eq("id", job["row_id"])
            .single()
            .execute()
        )
        template = row_result.data["csv_uploads"]["template"]

        supabase.table("jobs").update({"status": "processing"}).eq("id", job_id).execute()

        prompt = fill_template(template, row_data)
        content = generate_blog(prompt)

        supabase.table("blogs").insert(
            {
                "job_id": job_id,
                "content": content,
            }
        ).execute()

        supabase.table("jobs").update({"status": "completed"}).eq("id", job_id).execute()

        logger.info("Successfully generated blog for job %s", job_id)
    except Exception as exc:
        logger.error("Failed to generate blog for job %s: %s", job_id, exc)
        supabase.table("jobs").update(
            {
                "status": "failed",
                "error": str(exc),
            }
        ).eq("id", job_id).execute()
        raise
