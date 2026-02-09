# CSV Blog Generator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CSV upload endpoint that queues blog generation jobs via Celery, using OpenAI for content and Supabase for storage.

**Architecture:** FastAPI receives CSV + template, stores rows in Supabase, queues Celery tasks per row. Workers generate blogs via OpenAI and store results.

**Tech Stack:** FastAPI, Supabase, Celery, Redis, OpenAI API

---

## Task 1: Setup Dependencies & Configuration

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/config.py`
- Create: `backend/.env.example`

**Step 1: Update requirements.txt**

```txt
fastapi
uvicorn[standard]
supabase
celery[redis]
openai
python-multipart
python-dotenv
pydantic-settings
```

**Step 2: Create config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    openai_api_key: str
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"


settings = Settings()
```

**Step 3: Create .env.example**

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
OPENAI_API_KEY=sk-your-openai-key
REDIS_URL=redis://localhost:6379/0
```

**Step 4: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/.env.example
git commit -m "feat: add dependencies and configuration for CSV blog generator"
```

---

## Task 2: Supabase Database Client

**Files:**
- Create: `backend/app/database.py`

**Step 1: Create database.py**

```python
from supabase import create_client, Client

from app.config import settings

supabase: Client = create_client(settings.supabase_url, settings.supabase_key)
```

**Step 2: Commit**

```bash
git add backend/app/database.py
git commit -m "feat: add Supabase client"
```

---

## Task 3: Pydantic Models

**Files:**
- Create: `backend/app/models.py`

**Step 1: Create models.py**

```python
from pydantic import BaseModel
from typing import Any
from datetime import datetime


class UploadResponse(BaseModel):
    upload_id: str
    rows_count: int
    jobs_queued: int
    status: str


class UploadStatus(BaseModel):
    upload_id: str
    filename: str
    template: str
    total_jobs: int
    completed: int
    failed: int
    pending: int


class BlogItem(BaseModel):
    id: str
    row_data: dict[str, Any]
    content: str
    created_at: datetime


class BlogsResponse(BaseModel):
    blogs: list[BlogItem]
```

**Step 2: Commit**

```bash
git add backend/app/models.py
git commit -m "feat: add Pydantic models for API responses"
```

---

## Task 4: CSV Service

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/csv_service.py`

**Step 1: Create services directory and __init__.py**

```bash
mkdir -p backend/app/services
```

Create empty `__init__.py`:
```python
```

**Step 2: Create csv_service.py**

```python
import csv
import io
from typing import Any


def parse_csv(file_content: bytes) -> list[dict[str, Any]]:
    """Parse CSV content and return list of row dictionaries."""
    content = file_content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]


def fill_template(template: str, row_data: dict[str, Any]) -> str:
    """Fill template placeholders with row data values."""
    result = template
    for key, value in row_data.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result
```

**Step 3: Commit**

```bash
git add backend/app/services/
git commit -m "feat: add CSV parsing and template filling service"
```

---

## Task 5: OpenAI Service

**Files:**
- Create: `backend/app/services/openai_service.py`

**Step 1: Create openai_service.py**

```python
from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)


def generate_blog(prompt: str) -> str:
    """Generate blog content using OpenAI API."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Je bent een professionele blog schrijver. Schrijf informatieve, goed gestructureerde blogs in het Nederlands.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
    )
    return response.choices[0].message.content
```

**Step 2: Commit**

```bash
git add backend/app/services/openai_service.py
git commit -m "feat: add OpenAI service for blog generation"
```

---

## Task 6: Celery Worker Setup

**Files:**
- Create: `backend/app/worker/__init__.py`
- Create: `backend/app/worker/celery_app.py`

**Step 1: Create worker directory**

```bash
mkdir -p backend/app/worker
```

Create empty `__init__.py`:
```python
```

**Step 2: Create celery_app.py**

```python
from celery import Celery

from app.config import settings

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
    worker_concurrency=10,
)

celery_app.autodiscover_tasks(["app.worker"])
```

**Step 3: Commit**

```bash
git add backend/app/worker/
git commit -m "feat: add Celery app configuration"
```

---

## Task 7: Celery Tasks

**Files:**
- Create: `backend/app/worker/tasks.py`

**Step 1: Create tasks.py**

```python
from celery import shared_task
from celery.utils.log import get_task_logger

from app.database import supabase
from app.services.csv_service import fill_template
from app.services.openai_service import generate_blog

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_kwargs={"max_retries": 3},
)
def generate_blog_task(self, job_id: str):
    """Generate a blog for a specific job."""
    try:
        # Get job with row data
        job_result = supabase.table("jobs").select("*, csv_rows(*)").eq("id", job_id).single().execute()
        job = job_result.data
        row_data = job["csv_rows"]["data"]

        # Get upload for template
        row_result = supabase.table("csv_rows").select("*, csv_uploads(*)").eq("id", job["row_id"]).single().execute()
        template = row_result.data["csv_uploads"]["template"]

        # Update job status to processing
        supabase.table("jobs").update({"status": "processing"}).eq("id", job_id).execute()

        # Generate blog
        prompt = fill_template(template, row_data)
        content = generate_blog(prompt)

        # Save blog
        supabase.table("blogs").insert({
            "job_id": job_id,
            "content": content,
        }).execute()

        # Update job status to completed
        supabase.table("jobs").update({"status": "completed"}).eq("id", job_id).execute()

        logger.info(f"Successfully generated blog for job {job_id}")

    except Exception as e:
        logger.error(f"Failed to generate blog for job {job_id}: {e}")
        supabase.table("jobs").update({
            "status": "failed",
            "error": str(e),
        }).eq("id", job_id).execute()
        raise
```

**Step 2: Commit**

```bash
git add backend/app/worker/tasks.py
git commit -m "feat: add Celery task for blog generation"
```

---

## Task 8: CSV Upload Endpoint

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Update main.py with CSV upload endpoint**

```python
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.database import supabase
from app.models import UploadResponse, UploadStatus, BlogsResponse, BlogItem
from app.services.csv_service import parse_csv
from app.worker.tasks import generate_blog_task

app = FastAPI(
    title="FastAPI Backend",
    description="Backend API for CSV Blog Generator",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to FastAPI Backend"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.post("/api/csv/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    template: str = Form(...),
):
    """Upload a CSV file and queue blog generation jobs."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    # Read and parse CSV
    content = await file.read()
    rows = parse_csv(content)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # Create upload record
    upload_id = str(uuid.uuid4())
    supabase.table("csv_uploads").insert({
        "id": upload_id,
        "filename": file.filename,
        "template": template,
    }).execute()

    # Create rows and jobs
    jobs_queued = 0
    for row in rows:
        row_id = str(uuid.uuid4())
        supabase.table("csv_rows").insert({
            "id": row_id,
            "upload_id": upload_id,
            "data": row,
        }).execute()

        job_id = str(uuid.uuid4())
        supabase.table("jobs").insert({
            "id": job_id,
            "row_id": row_id,
            "status": "pending",
        }).execute()

        # Queue the task
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
    # Get upload
    upload_result = supabase.table("csv_uploads").select("*").eq("id", upload_id).single().execute()
    if not upload_result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    upload = upload_result.data

    # Get job counts
    jobs_result = supabase.table("jobs").select("status, csv_rows!inner(upload_id)").eq("csv_rows.upload_id", upload_id).execute()
    jobs = jobs_result.data

    total = len(jobs)
    completed = sum(1 for j in jobs if j["status"] == "completed")
    failed = sum(1 for j in jobs if j["status"] == "failed")
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
    # Verify upload exists
    upload_result = supabase.table("csv_uploads").select("id").eq("id", upload_id).single().execute()
    if not upload_result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    # Get blogs with row data
    blogs_result = supabase.table("blogs").select(
        "id, content, created_at, jobs!inner(csv_rows!inner(data, upload_id))"
    ).eq("jobs.csv_rows.upload_id", upload_id).execute()

    blogs = [
        BlogItem(
            id=b["id"],
            row_data=b["jobs"]["csv_rows"]["data"],
            content=b["content"],
            created_at=b["created_at"],
        )
        for b in blogs_result.data
    ]

    return BlogsResponse(blogs=blogs)
```

**Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add CSV upload and status endpoints"
```

---

## Task 9: Supabase Database Setup

**Files:**
- Create: `backend/supabase_schema.sql`

**Step 1: Create SQL schema file**

```sql
-- CSV Uploads table
CREATE TABLE csv_uploads (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    template TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- CSV Rows table
CREATE TABLE csv_rows (
    id UUID PRIMARY KEY,
    upload_id UUID REFERENCES csv_uploads(id) ON DELETE CASCADE,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Jobs table
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    row_id UUID REFERENCES csv_rows(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Blogs table
CREATE TABLE blogs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_csv_rows_upload_id ON csv_rows(upload_id);
CREATE INDEX idx_jobs_row_id ON jobs(row_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_blogs_job_id ON blogs(job_id);
```

**Step 2: Commit**

```bash
git add backend/supabase_schema.sql
git commit -m "feat: add Supabase database schema"
```

---

## Task 10: Final Testing & Documentation

**Files:**
- Modify: `backend/README.md` (create if not exists)

**Step 1: Create backend README**

```markdown
# CSV Blog Generator Backend

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your credentials

3. Run the Supabase schema in your Supabase SQL editor

4. Start Redis (required for Celery):
   ```bash
   redis-server
   ```

5. Start the Celery worker:
   ```bash
   celery -A app.worker.celery_app worker --loglevel=info
   ```

6. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

## API Endpoints

- `POST /api/csv/upload` - Upload CSV with template
- `GET /api/uploads/{upload_id}` - Get upload status
- `GET /api/uploads/{upload_id}/blogs` - Get generated blogs

## Example Usage

```bash
curl -X POST "http://localhost:8000/api/csv/upload" \
  -F "file=@blogs.csv" \
  -F "template=Schrijf een blog over {onderwerp} met focus op {keywords}"
```
```

**Step 2: Commit**

```bash
git add backend/README.md
git commit -m "docs: add backend README with setup instructions"
```

---

## Summary

After completing all tasks you will have:
- FastAPI endpoints for CSV upload and status tracking
- Supabase integration for data persistence
- Celery workers for background blog generation
- OpenAI integration for content generation
- Complete database schema
