# CSV Blog Generator Backend

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in credentials.

3. Run the Supabase schema in the Supabase SQL editor.

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
