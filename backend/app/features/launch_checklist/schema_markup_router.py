"""Ontbrekende JSON-LD voor één pagina van de livegang-scan ("Maak schema").

Synchroon (gewone `def`, draait in de threadpool): de pagina ophalen en één
modelaanroep, op verzoek van de gebruiker. De logica staat in `services/schema_markup.py`.
Het blok kopiëren kan altijd; met "Plaats in Rank Math" (`…/schema-markup/place`) zet
het dashboard het voorstel zelf op de WordPress-klantsite (`services/rankmath_schema.py`).
Alle endpoints per pagina geven dezelfde response terug.

In bulk (Schema-tabblad): genereren en plaatsen lopen per pagina via dezelfde endpoints. Een
collega keurt elk voorstel goed of af (`…/schema-markup/review`); bulkplaatsen gebruikt
`require_approved`, zodat er niets op de klantsite komt zonder goedkeuring van precies dat
voorstel. `…/schema-markup/overview` geeft de opgeslagen voorstellen van meerdere pagina's
(alleen database).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import LaunchScan, LaunchScanPage
from app.db.session import get_db
from app.features.launch_checklist.services.rankmath_schema import (
    PlacementState,
    RankMathPlacementBlocked,
    RankMathPlacementNotFound,
    RankMathSchemaError,
    place_schema,
    placement_state,
    remove_schema,
    review_schema,
)
from app.features.launch_checklist.services.schema_markup import (
    SchemaMarkupError,
    SchemaMarkupPageGoneError,
    SchemaMarkupResult,
    generate_schema_markup,
    stored_result,
)
from app.features.settings.services import MissingUserOpenAIKeyError

router = APIRouter(prefix="/api/launch-checklist", tags=["launch-checklist-schema-markup"])


class SchemaMarkupRequest(BaseModel):
    regenerate: bool = False


class SchemaPlaceRequest(BaseModel):
    # True (bulkroute) = alleen plaatsen als precies dit voorstel is goedgekeurd.
    require_approved: bool = False


class SchemaReviewRequest(BaseModel):
    status: Literal["pending", "approved", "rejected"]


MAX_OVERVIEW_PAGES = 200


class SchemaOverviewRequest(BaseModel):
    page_ids: list[str]


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
    # Types die al op de pagina staan en niet in het blok zijn herhaald; [] bij oude opslag.
    existing_types: list[str] = []
    # Plaatsing in Rank Math op de klantsite, of null.
    placement: SchemaPlacement | None = None
    can_place: bool = False
    # Eén zin waarom plaatsen niet kan; "" als can_place true is.
    place_blocked_reason: str = ""
    # Standaardtypes van Rank Math die bij plaatsen vervallen; [] als geen of onbekend.
    replaces_default_types: list[str] = []
    # Beoordeling van precies dit voorstel; "pending" na opnieuw genereren met andere JSON-LD.
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    # Wanneer goed- of afgekeurd; null bij "pending".
    reviewed_at: datetime | None = None


class SchemaPlacement(BaseModel):
    placed_at: datetime
    # De geplaatste types zijn teruggevonden in de HTML van de pagina.
    verified: bool
    # False = het voorstel is na het plaatsen opnieuw gegenereerd.
    current: bool
    site_name: str
    post_id: int


SchemaMarkupResponse.model_rebuild()


class SchemaOverviewItem(BaseModel):
    page_id: str
    url: str
    path: str
    title: str | None = None
    page_type: str | None = None
    # Het opgeslagen voorstel (`cached` true), of null als er nog geen voorstel is.
    result: SchemaMarkupResponse | None = None


class SchemaOverviewResponse(BaseModel):
    items: list[SchemaOverviewItem]


_PAGE_GONE = ("Pagina niet gevonden. Ze is intussen verwijderd, bijvoorbeeld door een nieuwe scan. "
              "Ververs de lijst en probeer het opnieuw.")


def _response(result: SchemaMarkupResult, state: PlacementState) -> SchemaMarkupResponse:
    placement = state.placement
    return SchemaMarkupResponse(
        script=result.script,
        types=result.types,
        placeholders=result.placeholders,
        notes=result.notes,
        problems=result.problems,
        generated_at=result.generated_at,
        cached=result.cached,
        nothing_missing=result.nothing_missing,
        existing_types=result.existing_types,
        placement=SchemaPlacement(**placement) if placement and placement.get("placed_at") else None,
        can_place=state.can_place,
        place_blocked_reason=state.reason,
        replaces_default_types=state.replaces_default_types,
        review_status=state.review_status,
        reviewed_at=state.reviewed_at,
    )


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
    # De sessie kan tijdens het genereren gesloten zijn; de pagina opnieuw ophalen.
    fresh = db.get(LaunchScanPage, page_id)
    if fresh is None:
        raise HTTPException(status_code=404, detail=_PAGE_GONE)
    return _response(result, placement_state(db, fresh, user_id, nothing_missing=result.nothing_missing))


def _stored_response(db: Session, page_id: str, user_id: str) -> SchemaMarkupResponse:
    page = db.get(LaunchScanPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail=_PAGE_GONE)
    result = stored_result(page)
    if result is None:
        raise HTTPException(status_code=404, detail="Er is geen schema-voorstel voor deze pagina.")
    return _response(result, placement_state(db, page, user_id))


def _placement_errors(exc: Exception, action: str) -> HTTPException:
    if isinstance(exc, RankMathPlacementBlocked):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, SchemaMarkupPageGoneError):
        return HTTPException(status_code=404, detail=_PAGE_GONE)
    # RankMathSchemaError (fout van de klantsite) of SchemaMarkupError (pagina niet op te halen).
    return HTTPException(status_code=502, detail=f"{action} {exc}")


@router.post("/scans/{scan_id}/pages/{page_id}/schema-markup/place", response_model=SchemaMarkupResponse)
def place_schema_markup(
    scan_id: str,
    page_id: str,
    payload: SchemaPlaceRequest | None = None,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Zet het opgeslagen voorstel in Rank Math op de klantsite (of werkt een plaatsing bij).

    Met `require_approved` (bulkroute) alleen als het huidige voorstel is goedgekeurd; anders
    400 zonder enige aanroep naar de klantsite.
    """
    page = db.get(LaunchScanPage, page_id)
    if page is None or not _page_in_scan(db, scan_id, page):
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")
    try:
        place_schema(db, page, user_id=user_id, require_approved=bool(payload and payload.require_approved))
    except (RankMathPlacementBlocked, RankMathSchemaError, SchemaMarkupPageGoneError, SchemaMarkupError) as exc:
        raise _placement_errors(exc, "Plaatsen in Rank Math is mislukt.") from exc
    return _stored_response(db, page_id, user_id)


@router.delete("/scans/{scan_id}/pages/{page_id}/schema-markup/place", response_model=SchemaMarkupResponse)
def remove_schema_markup(
    scan_id: str,
    page_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Haalt het geplaatste schema weg uit Rank Math op de klantsite."""
    page = db.get(LaunchScanPage, page_id)
    if page is None or not _page_in_scan(db, scan_id, page):
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")
    try:
        remove_schema(db, page, user_id=user_id)
    except RankMathPlacementNotFound as exc:
        raise HTTPException(status_code=404, detail="Er is geen geplaatst schema voor deze pagina.") from exc
    except (RankMathPlacementBlocked, RankMathSchemaError, SchemaMarkupPageGoneError) as exc:
        raise _placement_errors(exc, "Verwijderen uit Rank Math is mislukt.") from exc
    return _stored_response(db, page_id, user_id)


@router.put("/scans/{scan_id}/pages/{page_id}/schema-markup/review", response_model=SchemaMarkupResponse)
def review_schema_markup(
    scan_id: str,
    page_id: str,
    payload: SchemaReviewRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Keurt het huidige voorstel goed of af, of zet het terug naar "pending" (alleen database).

    Goedkeuren kan alleen als plaatsen mag (`can_place`); anders 400 met de reden.
    """
    page = db.get(LaunchScanPage, page_id)
    if page is None or not _page_in_scan(db, scan_id, page):
        raise HTTPException(status_code=404, detail="Pagina niet gevonden.")
    if stored_result(page) is None:
        raise HTTPException(status_code=404, detail="Er is geen schema-voorstel voor deze pagina.")
    try:
        review_schema(db, page, status=payload.status, user_id=user_id)
    except RankMathPlacementBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SchemaMarkupPageGoneError as exc:
        raise HTTPException(status_code=404, detail=_PAGE_GONE) from exc
    return _stored_response(db, page_id, user_id)


@router.post("/scans/{scan_id}/schema-markup/overview", response_model=SchemaOverviewResponse)
def schema_markup_overview(
    scan_id: str,
    payload: SchemaOverviewRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    """Opgeslagen voorstellen (met plaatsing en beoordeling) van meerdere pagina's.

    Alleen database: geen modelaanroep en geen HTTP naar de klantsite. Volgorde = `page_ids`;
    pagina's die niet bestaan of niet bij de scan horen worden weggelaten.
    """
    if len(payload.page_ids) > MAX_OVERVIEW_PAGES:
        raise HTTPException(status_code=400, detail=f"Vraag maximaal {MAX_OVERVIEW_PAGES} pagina's tegelijk op.")
    page_ids = list(dict.fromkeys(payload.page_ids))
    scan = db.get(LaunchScan, scan_id)
    scan_ids = {scan_id} | ({scan.source_scan_id} if scan is not None and scan.source_scan_id else set())
    rows = (
        db.query(LaunchScanPage)
        .filter(LaunchScanPage.id.in_(page_ids), LaunchScanPage.scan_id.in_(scan_ids))
        .all()
    ) if page_ids else []
    by_id = {row.id: row for row in rows}
    items: list[SchemaOverviewItem] = []
    for page_id in page_ids:
        page = by_id.get(page_id)
        if page is None:
            continue
        result = stored_result(page)
        items.append(SchemaOverviewItem(
            page_id=page.id,
            url=page.url,
            path=page.path,
            title=page.title,
            page_type=page.page_type,
            result=_response(result, placement_state(db, page, user_id)) if result is not None else None,
        ))
    return SchemaOverviewResponse(items=items)
