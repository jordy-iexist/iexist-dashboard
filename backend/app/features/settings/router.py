from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.session import get_db
from app.features.settings.schemas import (
    OpenAISettingsResponse,
    OpenAISettingsUpdateRequest,
)
from app.features.settings.services import (
    has_personal_openai_api_key,
    upsert_personal_openai_api_key,
)

router = APIRouter(tags=["settings"])


@router.get("/api/settings/openai", response_model=OpenAISettingsResponse)
async def get_openai_settings(
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    return OpenAISettingsResponse(
        has_personal_openai_api_key=has_personal_openai_api_key(user_id, db)
    )


@router.put("/api/settings/openai", response_model=OpenAISettingsResponse)
async def update_openai_settings(
    payload: OpenAISettingsUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    row = upsert_personal_openai_api_key(user_id, payload.openai_api_key, db)
    return OpenAISettingsResponse(
        has_personal_openai_api_key=bool(
            str(row.encrypted_openai_api_key or "").strip()
        )
    )
