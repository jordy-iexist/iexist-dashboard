# Full-Stack Application

This project contains a modern full-stack application with a Next.js frontend and FastAPI backend.

## Project Structure

```
test-claude-code/
├── frontend/          # Next.js application (TypeScript + Tailwind CSS)
└── backend/           # FastAPI application (Python)
```

## Frontend (Next.js)

### Tech Stack
- Next.js (latest version)
- TypeScript
- Tailwind CSS
- App Router
- ESLint

### Setup and Run

```bash
cd frontend
npm install          # Install dependencies (already done during creation)
npm run dev          # Start development server
```

The frontend will be available at [http://localhost:3000](http://localhost:3000)

### Other Commands

```bash
npm run build        # Build for production
npm start            # Start production server
npm run lint         # Run ESLint
```

## Backend (FastAPI)

### Tech Stack
- FastAPI
- Uvicorn
- Python 3.11+

### Setup and Run

```bash
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate   # On Windows

# Install dependencies
pip install -r requirements.txt

# Run the development server
uvicorn app.main:app --reload
```

The backend will be available at:
- API: [http://localhost:8000](http://localhost:8000)
- Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Alternative API docs: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### API Endpoints

- `GET /` - Root endpoint
- `GET /api/health` - Health check
- `GET /api/hello/{name}` - Example endpoint with path parameter

## Development Workflow

1. Start the backend server in one terminal
2. Start the frontend dev server in another terminal
3. The frontend is configured to communicate with the backend (CORS enabled for localhost:3000)

## Notes

- The backend includes CORS middleware configured to accept requests from the frontend
- Both projects have their own git repositories and can be managed independently
- The frontend uses the `src/` directory structure for better organization
- TypeScript and Tailwind CSS are pre-configured in the frontend

- uvicorn app.main:app --reload
- celery -A app.worker.celery_app worker --loglevel=info
- brew services start redis