from pathlib import Path
import time

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.auth import (
    authenticate_user,
    create_access_token,
    get_user_by_id,
    revoke_access_token,
    to_public_user,
)
from app.core.config import settings
from app.core.dependencies import require_user_id
from app.core.rate_limit import enforce_rate_limit
from app.storage import verify_signed_request as verify_storage_signature
from app.features.auth.schemas import AuthCredentialsRequest, AuthResponse, AuthUserItem

router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Welcome to FastAPI Backend"}


# Publieke registratie is uitgeschakeld. Accounts worden handmatig op de server
# aangemaakt via backend/scripts/create_user.py.


@router.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthCredentialsRequest, request: Request):
    enforce_rate_limit(request, "login", limit=10, window_seconds=60)
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
async def logout(
    authorization: str | None = Header(default=None),
    access_token: str | None = Cookie(default=None),
):
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif access_token and access_token.strip():
        token = access_token.strip()

    revoked = revoke_access_token(token) if token else False
    return {"status": "logged_out", "revoked": revoked}


@router.get("/api/storage/{bucket}/{storage_path:path}")
async def serve_storage_file(
    bucket: str,
    storage_path: str,
    exp: int = Query(...),
    sig: str = Query(...),
    download: bool = Query(default=False),
):
    now = int(time.time())
    if exp < now:
        raise HTTPException(status_code=410, detail="Afbeeldingslink is verlopen.")
    if not verify_storage_signature(bucket, storage_path, exp, sig):
        raise HTTPException(status_code=403, detail="Ongeldige afbeeldingslink.")

    file_path = Path(settings.storage_root).expanduser() / bucket / storage_path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Afbeelding niet gevonden.")
    if download:
        return FileResponse(file_path, filename=Path(storage_path).name)
    return FileResponse(file_path)
