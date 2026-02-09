import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.database import supabase
from app.models import BlogItem, BlogsResponse, UploadResponse, UploadStatus
from app.services.csv_service import parse_csv
from app.worker.tasks import generate_blog_task

app = FastAPI(
    title="FastAPI Backend",
    description="Backend API for CSV Blog Generator",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to FastAPI Backend"}

@app.post("/api/csv/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    template: str = Form(...),
):
    """Upload a CSV file and queue blog generation jobs."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    rows = parse_csv(content)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    upload_id = str(uuid.uuid4())
    supabase.table("csv_uploads").insert(
        {
            "id": upload_id,
            "filename": file.filename,
            "template": template,
        }
    ).execute()

    jobs_queued = 0
    for row in rows:
        row_id = str(uuid.uuid4())
        supabase.table("csv_rows").insert(
            {
                "id": row_id,
                "upload_id": upload_id,
                "data": row,
            }
        ).execute()

        job_id = str(uuid.uuid4())
        supabase.table("jobs").insert(
            {
                "id": job_id,
                "row_id": row_id,
                "status": "pending",
            }
        ).execute()

        generate_blog_task.delay(job_id)
        jobs_queued += 1

    return UploadResponse(
        upload_id=upload_id,
        rows_count=len(rows),
        jobs_queued=jobs_queued,
        status="processing",
    )


@app.get("/api/uploads/{upload_id}", response_model=UploadStatus)
async def get_upload_status(upload_id: str):
    """Get the status of an upload and its jobs."""
    upload_result = (
        supabase.table("csv_uploads").select("*").eq("id", upload_id).single().execute()
    )
    if not upload_result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    upload = upload_result.data

    jobs_result = (
        supabase.table("jobs")
        .select("status, csv_rows!inner(upload_id)")
        .eq("csv_rows.upload_id", upload_id)
        .execute()
    )
    jobs = jobs_result.data or []

    total = len(jobs)
    completed = sum(1 for job in jobs if job["status"] == "completed")
    failed = sum(1 for job in jobs if job["status"] == "failed")
    pending = total - completed - failed

    return UploadStatus(
        upload_id=upload_id,
        filename=upload["filename"],
        template=upload["template"],
        total_jobs=total,
        completed=completed,
        failed=failed,
        pending=pending,
    )


@app.get("/api/uploads/{upload_id}/blogs", response_model=BlogsResponse)
async def get_upload_blogs(upload_id: str):
    """Get all generated blogs for an upload."""
    upload_result = (
        supabase.table("csv_uploads").select("id").eq("id", upload_id).single().execute()
    )
    if not upload_result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    blogs_result = (
        supabase.table("blogs")
        .select("id, content, created_at, jobs!inner(csv_rows!inner(data, upload_id))")
        .eq("jobs.csv_rows.upload_id", upload_id)
        .execute()
    )

    blogs = [
        BlogItem(
            id=blog["id"],
            row_data=blog["jobs"]["csv_rows"]["data"],
            content=blog["content"],
            created_at=blog["created_at"],
        )
        for blog in (blogs_result.data or [])
    ]

    return BlogsResponse(blogs=blogs)
