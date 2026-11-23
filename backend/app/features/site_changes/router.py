"""Aanpassingen per pagina: inzien, beoordelen, afvinken en live controleren.

Er wordt niets naar WordPress geschreven; de medewerker voert wijzigingen zelf door en het
dashboard controleert het resultaat op de live pagina.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id
from app.db.models import (
    CustomerWebsite,
    LaunchContentPage,
    LaunchContentSuggestion,
    LaunchScan,
    LaunchScanIssue,
    SiteChange,
)
from app.db.session import get_db
from app.features.launch_checklist.services.discovery import url_key
from app.features.site_changes.mappers import (
    open_high_count,
    to_change_item,
    to_page_detail,
    to_page_summary,
    user_names,
)
from app.features.site_changes.schemas import (
    ChangeItem,
    ChangeUpdate,
    PageCheckRequest,
    PageCheckResponse,
    PageDetail,
    PagesResponse,
    PageTotals,
)
from app.features.site_changes.services import verify
from app.features.site_changes.services.changes import (
    APPROVED,
    DONE,
    KIND_ISSUE,
    KIND_SUGGESTION,
    OPEN,
    ChangeActionError,
    Entry,
    apply_action,
    mark_not_found,
    mark_verified,
    rebuild_scans,
    write_source_status,
)
from app.features.site_changes.services.sources import (
    PageInfo,
    absolute_url,
    collect_entries,
    path_of,
    schema_summary,
)

router = APIRouter(prefix="/api/site-changes", tags=["site-changes"])

NOT_FOUND_PAGE = "Geen aanpassingen gevonden voor deze pagina."
NOT_FOUND_ITEM = "Dit punt bestaat niet (meer). Ververs de pagina."


def _get_customer(db: Session, customer_id: str) -> CustomerWebsite:
    customer = db.get(CustomerWebsite, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")
    return customer


def _page_detail(
    db: Session, customer_id: str, ukey: str, *,
    transient: dict[str, tuple[dict[str, Any], bool | None]] | None = None, last_checked_at=None,
) -> PageDetail:
    sources, entries = collect_entries(db, customer_id, ukey)
    if not entries:
        raise HTTPException(status_code=404, detail=NOT_FOUND_PAGE)
    info = sources.pages.get(ukey) or PageInfo(url=entries[0].page_url, path=path_of(entries[0].page_url))
    return to_page_detail(
        info, entries, user_names(db, entries), schema_summary(db, customer_id, ukey),
        transient=transient, last_checked_at=last_checked_at,
    )


@router.get("/customers/{customer_id}/pages", response_model=PagesResponse)
async def list_pages(
    customer_id: str,
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_customer(db, customer_id)
    sources, entries = collect_entries(db, customer_id)
    by_page: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        by_page[entry.url_key].append(entry)
    pages = [
        to_page_summary(sources.pages.get(k) or PageInfo(url=es[0].page_url, path=path_of(es[0].page_url)), es)
        for k, es in by_page.items()
    ]
    pages.sort(key=lambda p: (-(p.open_count + p.approved_count), p.path))
    return PagesResponse(
        pages=pages,
        totals=PageTotals(
            open=sum(p.open_count for p in pages),
            approved=sum(p.approved_count for p in pages),
            done=sum(p.done_count for p in pages),
            open_high=open_high_count(entries),
        ),
        has_sources=sources.has_sources,
    )


@router.get("/customers/{customer_id}/page", response_model=PageDetail)
async def get_page(
    customer_id: str,
    url: str = Query(min_length=1, max_length=2000),
    _user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_customer(db, customer_id)
    return _page_detail(db, customer_id, url_key(url))


# --- beoordelen -------------------------------------------------------------------

def _entry_for_suggestion(db: Session, customer_id: str, suggestion_id: str) -> Entry | None:
    row = db.get(LaunchContentSuggestion, suggestion_id)
    if row is None or row.customer_website_id != customer_id or not row.content_page_id:
        return None
    page = db.get(LaunchContentPage, row.content_page_id)
    if page is None:
        return None
    _, entries = collect_entries(db, customer_id, url_key(page.url))
    return next(
        (e for e in entries if e.source is not None and e.source.source_ref.get("suggestion_id") == suggestion_id),
        None,
    )


def _entry_for_issue(db: Session, customer_id: str, issue_id: str) -> Entry | None:
    row = db.get(LaunchScanIssue, issue_id)
    if row is None or not row.url:
        return None
    scan = db.get(LaunchScan, row.scan_id)
    if scan is None or scan.customer_website_id != customer_id:
        return None
    _, entries = collect_entries(db, customer_id, url_key(absolute_url(row.url, scan.base_url)))
    return next(
        (e for e in entries if e.source is not None and any(i.id == issue_id for i in e.source.issues)),
        None,
    )


def _entry_for_key(db: Session, customer_id: str, key: str) -> Entry | None:
    row = (
        db.query(SiteChange)
        .filter(SiteChange.customer_website_id == customer_id, SiteChange.source_key == key)
        .first()
    )
    if row is None:
        return None
    _, entries = collect_entries(db, customer_id, row.url_key)
    return next((e for e in entries if e.key == key), None)


def _find_entry(db: Session, customer_id: str, payload: ChangeUpdate) -> Entry:
    entry: Entry | None = None
    ref = payload.source_ref
    if payload.source_kind == KIND_SUGGESTION and ref.suggestion_id:
        entry = _entry_for_suggestion(db, customer_id, ref.suggestion_id)
    elif payload.source_kind == KIND_ISSUE and ref.issue_id:
        entry = _entry_for_issue(db, customer_id, ref.issue_id)
    if entry is None:
        # Bron weg (heranalyse, nieuwe scan): verder op de bestaande rij met deze sleutel.
        entry = _entry_for_key(db, customer_id, payload.key)
    if entry is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_ITEM)
    if entry.kind != payload.source_kind:
        raise HTTPException(status_code=422, detail="Het soort punt klopt niet met de sleutel.")
    return entry


@router.put("/customers/{customer_id}/changes", response_model=ChangeItem)
async def update_change(
    customer_id: str,
    payload: ChangeUpdate,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_customer(db, customer_id)
    entry = _find_entry(db, customer_id, payload)
    names = user_names(db, [entry])
    before = to_change_item(entry, names)
    ukey, key = entry.url_key, entry.key
    try:
        apply_action(db, customer_id, entry, action=payload.action, user_id=user_id,
                     value=payload.value, note=payload.note)
    except ChangeActionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.commit()

    _, entries = collect_entries(db, customer_id, ukey)
    current = next((e for e in entries if e.key == key), None)
    if current is not None:
        return to_change_item(current, user_names(db, entries))
    # Heropend en de bron bestaat niet meer: het punt is weer 'open' zonder rij.
    return before.model_copy(update={
        "change_id": None, "status": OPEN, "approved_value": None, "edited": False, "verified": None,
        "verify_detail": None, "reviewed_by": None, "reviewed_at": None, "done_by": None, "done_at": None,
        "note": None,
    })


# --- live controleren -----------------------------------------------------------

STILL_PRESENT = "Treedt nog op op de live pagina."
RESOLVED = "Treedt niet meer op op de live pagina."


def _broken_candidates(entry: Entry) -> list[dict[str, Any]]:
    details = entry.source.details if entry.source is not None else None
    links = details.get("links") if isinstance(details, dict) else None
    return [link for link in links or [] if isinstance(link, dict) and link.get("url")]


@router.post("/customers/{customer_id}/page/check", response_model=PageCheckResponse)
async def check_page(
    customer_id: str,
    payload: PageCheckRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _get_customer(db, customer_id)
    ukey = url_key(payload.url)
    sources, entries = collect_entries(db, customer_id, ukey)
    if not entries:
        raise HTTPException(status_code=404, detail=NOT_FOUND_PAGE)

    suggestions = [
        e for e in entries
        if e.kind == KIND_SUGGESTION and e.status == APPROVED and e.row is not None and e.row.approved_value
        and verify.suggestion_checkable(e.topic, e.field("ref"), e.row.approved_value, e.page_url)
    ]
    issues = [
        e for e in entries
        if e.kind == KIND_ISSUE and e.status == OPEN and e.source is not None
        and verify.issue_checkable(e.source.type_key)
    ]
    if not suggestions and not issues:
        page = _page_detail(db, customer_id, ukey)
        return PageCheckResponse(page=page, checked=0, verified=0, resolved_issues=0)

    info = sources.pages.get(ukey)
    fetch_url = info.url if info is not None else entries[0].page_url
    try:
        live = verify.fetch_live(fetch_url)
    except verify.LiveFetchError as exc:
        raise HTTPException(status_code=502, detail=f"De live pagina kon niet worden gecontroleerd: {exc}") from exc
    checked_at = live.checked_at

    checked = verified = resolved = 0
    scans: list[LaunchScan | None] = []
    for entry in suggestions:
        result = verify.check_suggestion(entry.topic, entry.row.approved_value, entry.field("ref"), live)
        detail = verify.detail_of(result, checked_at)
        checked += 1
        if result.found:
            mark_verified(db, customer_id, entry, user_id=user_id, detail=detail)
            scans.append(write_source_status(db, entry, DONE, user_id))
            verified += 1
        else:
            mark_not_found(entry, detail)

    transient: dict[str, tuple[dict[str, Any], bool | None]] = {}
    if issues:
        determinable = verify.determinable_types(live)
        candidates = [link for e in issues if e.source.type_key == "broken_links" for link in _broken_candidates(e)]
        present = verify.live_issue_types(live, candidates)
        for entry in issues:
            issue_type = entry.source.type_key
            if issue_type not in determinable or (issue_type == "broken_links" and not _broken_candidates(entry)):
                message = (
                    f"De pagina stuurt door naar {live.final_url}; controleer de eindpagina."
                    if live.redirected else "Niet automatisch te controleren voor deze pagina."
                )
                transient[entry.key] = (
                    verify.detail_of(verify.CheckResult(False, message), checked_at), None)
                continue
            checked += 1
            if issue_type in present:
                transient[entry.key] = (
                    verify.detail_of(verify.CheckResult(False, STILL_PRESENT), checked_at), False)
                continue
            detail = verify.detail_of(verify.CheckResult(True, RESOLVED), checked_at)
            mark_verified(db, customer_id, entry, user_id=user_id, detail=detail)
            write_source_status(db, entry, DONE, user_id)
            resolved += 1

    rebuild_scans(db, scans)
    db.commit()
    page = _page_detail(db, customer_id, ukey, transient=transient, last_checked_at=checked_at)
    return PageCheckResponse(page=page, checked=checked, verified=verified, resolved_issues=resolved)
