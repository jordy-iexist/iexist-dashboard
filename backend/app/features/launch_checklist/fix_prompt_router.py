"""Opdracht voor Claude Code bij één actiepunt van de livegang-checklist ("Maak prompt").

Synchroon (gewone `def`, draait in de threadpool): één modelaanroep voor één
punt, op verzoek van de gebruiker. De logica staat in `services/fix_prompt.py`.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import LaunchScanIssue
from app.db.session import get_db
from app.features.launch_checklist.services.fix_prompt import (
    FixPromptError,
    FixPromptIssueGoneError,
    generate_fix_prompt,
)
from app.features.settings.services import MissingUserOpenAIKeyError

router = APIRouter(prefix="/api/launch-checklist", tags=["launch-checklist-fix-prompt"])


class FixPromptRequest(BaseModel):
    regenerate: bool = False


class FixPromptResponse(BaseModel):
    prompt: str
    generated_at: datetime
    # True = opgeslagen opdracht teruggegeven, zonder modelaanroep.
    cached: bool


@router.post("/issues/{issue_id}/fix-prompt", response_model=FixPromptResponse)
def create_fix_prompt(
    issue_id: str,
    payload: FixPromptRequest | None = None,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    issue = db.get(LaunchScanIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Actiepunt niet gevonden.")
    try:
        prompt, generated_at, cached = generate_fix_prompt(
            db, issue, user_id=user_id, regenerate=bool(payload and payload.regenerate)
        )
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(
            status_code=400,
            detail="Er is geen OpenAI API-key ingesteld. Voeg je key toe bij Instellingen en probeer het opnieuw.",
        ) from exc
    except FixPromptIssueGoneError as exc:
        raise HTTPException(
            status_code=404,
            detail="Actiepunt niet gevonden. Het is tijdens het maken van de prompt verwijderd, "
            "bijvoorbeeld door een nieuwe scan. Ververs de lijst en probeer het opnieuw.",
        ) from exc
    except FixPromptError as exc:
        raise HTTPException(status_code=502, detail=f"De prompt kon niet worden gemaakt. {exc}") from exc
    return FixPromptResponse(prompt=prompt, generated_at=generated_at, cached=cached)
