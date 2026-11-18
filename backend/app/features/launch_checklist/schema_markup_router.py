"""Ontbrekende JSON-LD voor één pagina van de livegang-scan ("Maak schema").

Synchroon (gewone `def`, draait in de threadpool): de pagina ophalen en één
modelaanroep, op verzoek van de gebruiker. De logica staat in `services/schema_markup.py`.
Er wordt niets op de klantsite geschreven; de collega kopieert het blok zelf.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import LaunchScan, LaunchScanPage
from app.db.session import get_db
from app.features.launch_checklist.services.schema_markup import (
    SchemaMarkupError,
    SchemaMarkupPageGoneError,
    generate_schema_markup,
)
from app.features.settings.services import MissingUserOpenAIKeyError

router = APIRouter(prefix="/api/launch-checklist", tags=["launch-checklist-schema-markup"])


class SchemaMarkupRequest(BaseModel):
    regenerate: bool = False


class SchemaMarkupResponse(BaseModel):
    # Volledig <script type="application/ld+json">-blok; leeg als er niets ontbreekt.
    script: str
    types: list[str]
    # Plaatshouders in het blok die de collega nog moet invullen.
    placeholders: list[str]
    notes: str
    # Validatieproblemen (fouten en waarschuwingen) als leesbare regels.
    problems: list[str]
    generated_at: datetime
    # True = opgeslagen schema teruggegeven, zonder modelaanroep.
    cached: bool
    # True = het verwachte schema staat er al; geen modelaanroep, niets opgeslagen.
    nothing_missing: bool


def _page_in_scan(db: Session, scan_id: str, page: LaunchScanPage) -> bool:
    """De pagina hoort bij de scan zelf of (fase 2) bij de bronscan ervan."""
    if page.scan_id == scan_id:
        return True
    scan = db.get(LaunchScan, scan_id)
    return scan is not None and scan.source_scan_id == page.scan_id


@router.post("/scans/{scan_id}/pages/{page_id}/schema-markup", response_model=SchemaMarkupResponse)
def create_schema_markup(
    scan_id: str,
    page_id: str,
    payload: SchemaMarkupRequest | None = None,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    page = db.get(LaunchScanPage, page_id)
    if page is None or not _page_in_scan(db, scan_id, page):
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")
    try:
        result = generate_schema_markup(
            db, page, user_id=user_id, regenerate=bool(payload and payload.regenerate)
        )
    except MissingUserOpenAIKeyError as exc:
        raise HTTPException(
            status_code=400,
            detail="Er is geen OpenAI API-key ingesteld. Voeg je key toe bij Instellingen en probeer het opnieuw.",
        ) from exc
    except SchemaMarkupPageGoneError as exc:
        raise HTTPException(
            status_code=404,
            detail="Pagina niet gevonden. Ze is tijdens het maken van het schema verwijderd, "
            "bijvoorbeeld door een nieuwe scan. Ververs de lijst en probeer het opnieuw.",
        ) from exc
    except SchemaMarkupError as exc:
        raise HTTPException(status_code=502, detail=f"Het schema kon niet worden gemaakt. {exc}") from exc
    return SchemaMarkupResponse(
        script=result.script,
        types=result.types,
        placeholders=result.placeholders,
        notes=result.notes,
        problems=result.problems,
        generated_at=result.generated_at,
        cached=result.cached,
        nothing_missing=result.nothing_missing,
    )
