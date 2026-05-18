# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **CSV Blog Generator** - a full-stack application that accepts CSV files and generates blog posts using OpenAI's GPT-4o-mini model. Generated content is stored in Supabase PostgreSQL, with background processing via Celery + Redis.

**Architecture Pattern**: Async job queue system where CSV uploads trigger background OpenAI generation tasks.

## Development Commands

### Frontend (Next.js)

```bash
cd frontend
npm install              # Install dependencies
npm run dev             # Start dev server (localhost:3000)
npm run build           # Build for production
npm start               # Start production server
npm run lint            # Run ESLint
```

### Backend (FastAPI)

```bash
cd backend
python3 -m venv venv                    # Create virtual environment
source venv/bin/activate                # Activate (macOS/Linux)
pip install -r requirements.txt         # Install dependencies
uvicorn app.main:app --reload           # Start dev server (localhost:8000)
```

### Background Worker (Celery)

```bash
# Start Redis (required for Celery)
brew services start redis               # macOS
# Or: redis-server                       # Direct start

# Start Celery worker (in backend directory)
celery -A app.worker.celery_app worker --loglevel=info
```

## Architecture Overview

### Backend Architecture (FastAPI)

- **API-first design**: RESTful endpoints for CSV upload and job status tracking
- **Background processing**: Celery + Redis for async OpenAI API calls
- **Database pattern**: SQLAlchemy via custom PostgREST-compatible client
- **Task queuing**: Each CSV row becomes a separate Celery job
- **Status flow**: `pending` → `processing` → `completed`/`failed`

**Key backend modules**:
- `app/main.py` - FastAPI app with CORS and router registration
- `app/core/config.py` - Configuration management (Pydantic Settings)
- `app/core/dependencies.py` - Shared auth dependencies (`require_user_id`, `utc_now_iso`)
- `app/db/models.py` - All SQLAlchemy models (monolithic, Alembic-safe)
- `app/db/session.py` - Database session factory
- `app/api/router.py` - Root router; includes feature routers + system router
- `app/api/system.py` - Auth and storage endpoints
- `app/features/blogs/` - Blog generation, images, WordPress publishing
- `app/features/seo_tracker/` - CustomerWebsite CRUD, keywords, SERP scans, rankings
- `app/features/seo_meta/` - Meta run management and page meta optimization
- `app/services/openai/` - Shared OpenAI client (used by blogs + seo_meta)
- `app/worker/tasks.py` - Re-exports all Celery tasks from feature workers
- `app/worker/celery_app.py` - Celery app configuration

**Feature module structure** (same pattern for all 3 features):
```
features/<feature>/
  router.py        - FastAPI APIRouter with all HTTP endpoints
  schemas.py       - Pydantic request/response models
  mappers.py       - dict-to-schema conversion functions
  dependencies.py  - feature-specific FastAPI dependencies (blogs only)
  services/        - business logic (pure Python, no HTTP)
  worker/          - Celery task definitions
```

### Frontend Architecture (Next.js 16)

- **App Router**: Route groups for `(auth)` and `(protected)` pages
- **Authentication**: Supabase SSR with middleware-based route protection
- **Component pattern**: Radix UI primitives with Tailwind CSS v4
- **API proxying**: Frontend communicates with backend via `/api/*` routes

**Key frontend directories**:
- `src/app/(auth)/` - Login/signup pages (public)
- `src/app/(protected)/` - Dashboard pages (require auth)
- `src/app/api/` - Next.js API routes that proxy to FastAPI backend
- `src/lib/` - Supabase client and utilities

### Data Flow

1. **CSV Upload**: Frontend → FastAPI `/api/csv/upload` → Parse CSV → Store rows in Supabase
2. **Job Creation**: Create Celery task for each CSV row → Queue in Redis
3. **Background Processing**: Celery worker picks job → Generate prompt → Call OpenAI → Store blog
4. **Status Tracking**: Frontend polls `/api/uploads/{upload_id}` for progress

### Database Schema (Supabase PostgreSQL)

Four main tables managed by backend:
- `csv_uploads` - Upload metadata (filename, template)
- `csv_rows` - Individual CSV rows as JSON
- `jobs` - Job status tracking (links rows to blogs)
- `blogs` - Generated blog content

All database operations use the Supabase Python client directly (no ORM).

## Technology Stack

### Frontend
- **Next.js 16.1.3** (App Router, React 19.2.3, TypeScript)
- **Tailwind CSS v4** with PostCSS integration
- **Supabase SSR** for authentication
- **Radix UI** for component primitives

### Backend
- **FastAPI** with Uvicorn
- **Celery** with Redis broker
- **OpenAI API** (gpt-4o-mini model)
- **Supabase Python client**
- **Pydantic** for data validation

## Configuration

### Environment Variables

**Backend** (`backend/.env`):
```
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/csv_blog_generator
OPENAI_API_KEY=
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=
```

**Frontend** (`frontend/.env.local`):
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

### MCP Integration

The project includes an MCP server configuration (`.mcp.json`) for Supabase:
- Connects to local Supabase instance at `http://localhost:54321/mcp`
- Enables direct database access via MCP tools

## Next.js Development with MCP

**CRITICAL: When working on the Next.js frontend, ALWAYS call the `init` tool from next-devtools-mcp FIRST to set up proper context and establish documentation requirements. Do this automatically without being asked.**

This ensures:
- All Next.js queries use official documentation via `nextjs_docs` tool
- Proper context for runtime diagnostics via `nextjs_index` and `nextjs_call`
- Correct two-step documentation workflow: search → get

**Workflow:**
1. Start by calling `init` from next-devtools-mcp
2. Use `nextjs_docs({ action: "search", query: "..." })` to find documentation
3. Use `nextjs_docs({ action: "get", path: "..." })` to retrieve full content
4. Use `nextjs_index` to discover running dev servers
5. Use `nextjs_call` to query runtime state (errors, logs, routes)

## Important Development Notes

### Celery Worker Requirements
- **Redis must be running** before starting Celery worker
- Celery task definitions are in `app/worker/tasks.py`
- Use `celery -A app.worker.celery_app worker --loglevel=info` to start

### Frontend-Backend Communication
- Frontend uses Next.js API routes (`/api/*`) to proxy requests to FastAPI
- CORS is configured in FastAPI to allow `localhost:3000`
- Backend runs on port 8000, frontend on port 3000

### Next.js 16 Specifics
- Uses modern **App Router** with route groups
- Middleware is now called **`proxy.ts`** (not `middleware.ts`)
- Supabase SSR requires dynamic rendering in auth routes

### Database Operations
- Backend uses a custom SQLAlchemy-based client that mimics the PostgREST API
- All database logic is in `app/db/client.py` and service files
- MCP tools can query the database directly when server is running

## Testing

No automated tests are currently configured. Manual testing workflow:
1. Start Redis: `brew services start redis`
2. Start Celery worker: `celery -A app.worker.celery_app worker --loglevel=info`
3. Start FastAPI backend: `uvicorn app.main:app --reload`
4. Start Next.js frontend: `cd frontend && npm run dev`
5. Access frontend at `http://localhost:3000`
6. API documentation at `http://localhost:8000/docs`


<claude-mem-context>
# Recent Activity

<!-- This section is auto-generated by claude-mem. Edit content outside the tags. -->

*No recent activity*
</claude-mem-context>