# CSV Blog Generator Backend

## Runtime stack

Deze backend draait nu als self-hosted stack met:

- FastAPI API container
- Celery worker container
- PostgreSQL 16
- Redis 7
- Lokale filesystem media-opslag via een Docker volume

De root `docker-compose.yml` orkestreert alle services. De media-opslag wordt gedeeld tussen API en worker via de named volume `backend_media`.

## Docker setup

1. Kopieer `backend/.env.example` naar `backend/.env` en vul de secrets in.
   - Minimaal verplicht:
     - `DATABASE_URL`
     - `JWT_SECRET_KEY`
     - `WORDPRESS_CREDENTIALS_KEY`
   - Voor SEO scans:
     - `SERPAPI_API_KEY`
   - Voor OpenAI-features moet iedere gebruiker daarna in `/dashboard/settings` een eigen OpenAI API key instellen.
   - Vervang een oude `.env` volledig; laat geen verouderde database- of localhost-waarden staan als bron van waarheid voor de nieuwe stack.

2. Start de stack vanuit de repository root:
   ```bash
   docker compose up --build
   ```

3. Beschikbare services:
   - API: `http://localhost:8000`
   - Postgres: `localhost:5432`
   - Redis: `localhost:6379`

## Belangrijke env vars

```env
DATABASE_URL=postgresql+psycopg://csv_blog_generator:csv_blog_generator@db:5432/csv_blog_generator
REDIS_URL=redis://redis:6379/0
JWT_SECRET_KEY=change-me
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRES_MINUTES=10080
STORAGE_SIGNING_SECRET=change-me-storage-secret
MEDIA_ROOT=/app/media
MEDIA_BASE_URL=http://localhost:8000
```

### Notes

- `DATABASE_URL` wijst in Docker naar service `db`.
- `REDIS_URL` wijst in Docker naar service `redis`.
- `MEDIA_ROOT` is de map waar uploads/generated images fysiek worden opgeslagen.
- `MEDIA_BASE_URL` is de publieke backend-origin die wordt gebruikt voor media-URLs.
- `STORAGE_SIGNING_SECRET` tekent tijdelijke afbeeldings-URLs voor de lokale storage-backend.

## Lokale processen zonder Docker

Als je de stack lokaal zonder Compose wilt draaien:

1. Installeer dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Start Postgres en Redis lokaal of via losse containers.

3. Zet in `backend/.env` de juiste lokale waarden, bijvoorbeeld:
   ```env
   DATABASE_URL=postgresql+psycopg://csv_blog_generator:csv_blog_generator@localhost:5432/csv_blog_generator
   REDIS_URL=redis://localhost:6379/0
   MEDIA_ROOT=./media
   MEDIA_BASE_URL=http://localhost:8000
   ```

4. Start de API:
   ```bash
   uvicorn app.main:app --reload
   ```

5. Start de worker:
   ```bash
   celery -A app.worker.celery_app worker --loglevel=info -Q default,blog_generation,image_generation --concurrency=3
   ```

## API Endpoints

- `POST /api/csv/upload` - Upload CSV with template
- `GET /api/uploads/{upload_id}` - Get upload status
- `GET /api/uploads/{upload_id}/blogs` - Get generated blogs
- `POST /api/wordpress/sites` - Add WordPress site connection
- `GET /api/wordpress/sites` - List WordPress site connections
- `PATCH /api/wordpress/sites/{site_id}` - Update/deactivate WordPress site
- `POST /api/blogs/{blog_id}/publish` - Publish one blog to one/multiple sites
- `POST /api/blogs/publish/batch` - Batch publish multiple blogs to multiple sites
- `GET /api/publications/{publication_id}` - Get one publication status
- `GET /api/publications?blog_id={blog_id}` - List publication history
- `GET /api/blogs/{blog_id}/images` - List blog images (manual + auto)
- `GET /api/blogs/{blog_id}/images/generation-status` - Get auto-image generation status/progress
- `POST /api/blogs/{blog_id}/images/upload` - Upload/replace manual primary image
- `POST /api/blogs/{blog_id}/images/generate` - Queue auto image generation
- `POST /api/seo/websites` - Add a customer website for SEO tracking
- `GET /api/seo/websites` - List customer websites
- `PATCH /api/seo/websites/{website_id}` - Update/deactivate a customer website
- `DELETE /api/seo/websites/{website_id}` - Delete a customer website (+ cascades keywords/scans/results)
- `POST /api/seo/websites/{website_id}/keywords` - Add keyword for a website
- `GET /api/seo/websites/{website_id}/keywords` - List keywords for a website
- `PATCH /api/seo/keywords/{keyword_id}` - Update keyword text/active status
- `DELETE /api/seo/keywords/{keyword_id}` - Delete one keyword
- `POST /api/seo/websites/{website_id}/scan` - Queue a manual SerpApi scan
- `GET /api/seo/scans/{scan_id}` - Get one scan status/progress
- `POST /api/seo/scans/{scan_id}/cancel` - Cancel a running/pending scan
- `GET /api/seo/websites/{website_id}/scans` - List scan history for one website
- `GET /api/seo/websites/{website_id}/rankings` - Get latest + previous ranking positions

## Example Usage

```bash
curl -X POST "http://localhost:8000/api/csv/upload" \
  -F "file=@blogs.csv" \
  -F "template=Schrijf een blog over {onderwerp} met focus op {keywords}"
```
