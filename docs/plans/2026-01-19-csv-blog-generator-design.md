# CSV Blog Generator Design

## Overview

Een systeem dat CSV bestanden accepteert, per rij een blog genereert via OpenAI, en alles opslaat in Supabase.

## Architectuur

### Componenten
- **FastAPI Backend**: CSV upload endpoint, job management API
- **Supabase PostgreSQL**: Opslag voor CSV data, jobs, en gegenereerde blogs
- **Redis**: Message broker voor de job queue
- **Celery Worker**: Background verwerking van OpenAI API calls

### Flow
1. Gebruiker uploadt CSV + prompt template
2. Backend parsed CSV en slaat rijen op in Supabase
3. Per rij wordt een job aangemaakt in de queue
4. Celery worker pakt jobs op, genereert prompts, roept OpenAI aan
5. Gegenereerde blogs worden opgeslagen in Supabase

## Database Tabellen

- `csv_uploads`: Upload metadata (id, filename, template, created_at)
- `csv_rows`: Individuele rijen als JSON (id, upload_id, data, created_at)
- `jobs`: Job status tracking (id, row_id, status, error, created_at)
- `blogs`: Gegenereerde content (id, job_id, content, created_at)

## API Endpoints

### POST /api/csv/upload
```
Request:
- file: CSV bestand (multipart/form-data)
- template: string (bijv. "Schrijf een blog over {onderwerp} met focus op {keywords}")

Response:
{
  "upload_id": "uuid",
  "rows_count": 25,
  "jobs_queued": 25,
  "status": "processing"
}
```

### GET /api/uploads/{upload_id}
```
Response:
{
  "upload_id": "uuid",
  "filename": "blogs.csv",
  "template": "...",
  "total_jobs": 25,
  "completed": 10,
  "failed": 1,
  "pending": 14
}
```

### GET /api/uploads/{upload_id}/blogs
```
Response:
{
  "blogs": [
    {"id": "uuid", "row_data": {...}, "content": "...", "created_at": "..."},
    ...
  ]
}
```

## Background Worker

### Celery Task Flow
```python
@celery.task
def generate_blog(job_id):
    1. Haal job + row data op uit Supabase
    2. Vul template in met kolomwaarden
    3. Roep OpenAI API aan (gpt-4o-mini)
    4. Sla blog op in Supabase
    5. Update job status naar "completed" of "failed"
```

### Error Handling
- Retry mechanisme: 3 pogingen met exponential backoff
- Bij permanente fout: job status -> "failed" met error message
- Rate limiting: max 10 concurrent OpenAI calls

## Environment Variables

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `OPENAI_API_KEY`
- `REDIS_URL`

## Project Structuur

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + endpoints
│   ├── config.py            # Environment variables
│   ├── database.py          # Supabase client
│   ├── models.py            # Pydantic schemas
│   ├── services/
│   │   ├── csv_service.py   # CSV parsing logic
│   │   └── openai_service.py # OpenAI API calls
│   └── worker/
│       ├── celery_app.py    # Celery configuratie
│       └── tasks.py         # Background tasks
├── requirements.txt
└── .env
```

## Dependencies

- `supabase` - Database client
- `celery[redis]` - Background worker
- `openai` - OpenAI API
- `python-multipart` - File uploads
- `python-dotenv` - Environment variables
