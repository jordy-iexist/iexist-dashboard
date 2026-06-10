from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router as api_router
from app.core.config import settings, validate_required_secrets
from app.db.session import engine
from app.db.models import Base


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_required_secrets(settings)
    # Create all tables that don't exist yet (safe for new deployments).
    # For schema changes on existing tables, use Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="FastAPI Backend",
    description="Backend API for CSV Blog Generator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
