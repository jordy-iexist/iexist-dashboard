from pathlib import Path
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.auth import (
    authenticate_user,
    create_access_token,
    create_user,
    get_user_by_email,
    get_user_by_id,
    to_public_user,
)
from app.core.config import settings
from app.core.dependencies import require_user_id
from app.storage import verify_signed_request as verify_storage_signature
from app.features.auth.schemas import AuthCredentialsRequest, AuthResponse, AuthUserItem

router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to FastAPI Backend"}


@router.post("/api/auth/signup", response_model=AuthResponse)
async def signup(payload: AuthCredentialsRequest):
    email = str(payload.email or "").strip().lower()
    password = str(payload.password or "")
    if not email:
        raise HTTPException(status_code=400, detail="E-mailadres is verplicht.")
    if len(password) < 8:
        raise HTTPException(
            status_code=400, detail="Wachtwoord moet minimaal 8 tekens lang zijn."
        )

    if get_user_by_email(email):
        raise HTTPException(
            status_code=409, detail="Er bestaat al een account met dit e-mailadres."
        )

    try:
        user = create_user(email, password)
    except ValueError as exc:
        message = str(exc).lower()
        if "unique" in message and "email" in message:
            raise HTTPException(
                status_code=409,
                detail="Er bestaat al een account met dit e-mailadres.",
            ) from exc
        raise HTTPException(
            status_code=400,
            detail="Account aanmaken mislukt.",
        ) from exc
    token = create_access_token(user_id=str(user["id"]), email=str(user["email"]))
    return AuthResponse(
        access_token=token,
        user=AuthUserItem(**to_public_user(user)),
    )


@router.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthCredentialsRequest):
    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Ongeldige inloggegevens.")

    token = create_access_token(user_id=str(user["id"]), email=str(user["email"]))
    return AuthResponse(
        access_token=token,
        user=AuthUserItem(**to_public_user(user)),
    )


@router.get("/api/auth/me", response_model=AuthUserItem)
async def get_authenticated_user(user_id: str = Depends(require_user_id)):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Gebruiker niet gevonden.")
    return AuthUserItem(**to_public_user(user))


@router.post("/api/auth/logout")
async def logout():
    return {"status": "logged_out"}


@router.get("/api/storage/{bucket}/{storage_path:path}")
async def serve_storage_file(
    bucket: str,
    storage_path: str,
    exp: int = Query(...),
    sig: str = Query(...),
):
    now = int(time.time())
    if exp < now:
        raise HTTPException(status_code=410, detail="Afbeeldingslink is verlopen.")
    if not verify_storage_signature(bucket, storage_path, exp, sig):
        raise HTTPException(status_code=403, detail="Ongeldige afbeeldingslink.")

    file_path = Path(settings.storage_root).expanduser() / bucket / storage_path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Afbeelding niet gevonden.")
    return FileResponse(file_path)
