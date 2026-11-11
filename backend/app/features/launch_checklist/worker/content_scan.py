"""Celery-tasks: livegang fase 3 (Contentcreatie & Onpage optimalisatie).

Twee stappen:
1. `run_content_scan_task`: haalt de HTML van de fase-1 pagina's opnieuw op,
   bewaart de inhoud per pagina, controleert interne links op 404's/redirects,
   draait de regelcontrole en maakt checklist + actiepunten. Geen AI.
2. `run_content_analysis_task`: draait de AI-agents op de pagina's die de
   gebruiker heeft geselecteerd, daarna de contentgap- en rapport-agent.
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.core.url_guard import is_safe_external_url
from app.db.models import (
    CustomerWebsite,
    LaunchChecklistState,
    LaunchContentPage,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.db.session import SessionLocal
from app.features.launch_checklist.services import ahrefs_enrich
from app.features.launch_checklist.services.content_analysis import (
    Usage,
    analyse_page,
    run_gap,
    run_report,
)
from app.features.launch_checklist.services.content_extract import extract_content
from app.features.launch_checklist.services.content_rebuild import (
    build_content_payload,
    content_pages,
    rebuild_content_checklist,
    reset_unfinished_analysis,
)
from app.features.launch_checklist.services.discovery import root_domain_of, url_key
from app.features.launch_checklist.services.inventory import (
    MAX_BODY_BYTES,
    _INCONCLUSIVE_STATUSES,
    _looks_like_page,
    _new_client,
    _path_of,
)
from app.features.launch_checklist.services.issue_state import (
    previous_issue_state,
    with_carried_state,
)
from app.features.launch_checklist.services.issues import _is_ok_html, generate_content_issues
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}
BATCH_SIZE = 20
MAX_LINK_CHECKS = 800
LINK_CHECK_CONCURRENCY = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status_of(scan_id: str) -> str | None:
    with SessionLocal() as db:
        row = db.query(LaunchScan.status).filter(LaunchScan.id == scan_id).first()
        return str(row[0] or "").lower() if row else None


def _is_stopped(scan_id: str) -> bool:
    status = _status_of(scan_id)
    return status is None or status in STOPPED_STATUSES


def _update(scan_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(LaunchScan).filter(
            LaunchScan.id == scan_id, LaunchScan.status != "canceled"
        ).update(fields, synchronize_session=False)
        db.commit()


# --- stap 1: scan -----------------------------------------------------------------

def _with_ahrefs_signal(fields: dict[str, Any], hint: dict[str, Any] | None) -> dict[str, Any]:
    """Bewaar het Ahrefs-topzoekwoord (met positie en volume) bij de signalen van de pagina."""
    if not hint:
        return fields
    return {**fields, "signals": {**(fields.get("signals") or {}), "ahrefs": hint}}


async def _fetch_content(
    targets: list[dict[str, Any]], root_domain: str, concurrency: int, on_batch: Any,
) -> dict[str, dict[str, Any]]:
    """targets: [{id, url}] → {source_page_id: velden voor LaunchContentPage}."""
    results: dict[str, dict[str, Any]] = {}
    sem = asyncio.Semaphore(concurrency)

    async with _new_client(concurrency, 20.0) as client, _new_client(concurrency, 20.0, http2=False) as h1:

        async def one(target: dict[str, Any]) -> None:
            url = target["url"]
            if not is_safe_external_url(url):
                return
            async with sem:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 403:
                        resp = await h1.get(url)
                except httpx.HTTPError:
                    return
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "").lower():
                return
            html = resp.content[:MAX_BODY_BYTES].decode(resp.encoding or "utf-8", errors="replace")
            extracted = extract_content(html, str(resp.url), root_domain)
            results[target["id"]] = {
                "title": extracted.title,
                "meta_description": extracted.meta_description,
                "headings": extracted.headings,
                "body_text": extracted.body_text,
                "first_paragraph": extracted.first_paragraph,
                "word_count": extracted.word_count,
                "images": extracted.images,
                "links": extracted.links,
                "signals": extracted.signals,
            }

        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start: start + BATCH_SIZE]
            await asyncio.gather(*(one(t) for t in batch))
            if not on_batch(start + len(batch)):
                break
    return results


async def _check_links(urls: list[str], known_ok: set[str]) -> dict[str, dict[str, Any]]:
    """Status van interne linkdoelen: {url_key: {status, broken, redirect, final_url}}.

    Pagina's die net met 200 zijn opgehaald hoeven niet opnieuw; de rest krijgt
    één verzoek zonder redirects te volgen, en bij een redirect nog één mét.
    """
    out: dict[str, dict[str, Any]] = {key: {"status": 200, "broken": False, "redirect": False} for key in known_ok}
    todo: list[str] = []
    seen: set[str] = set(known_ok)
    for url in urls:
        key = url_key(url)
        if key in seen or not _looks_like_page(url):
            continue
        seen.add(key)
        todo.append(url)
    todo = todo[:MAX_LINK_CHECKS]
    sem = asyncio.Semaphore(LINK_CHECK_CONCURRENCY)

    async with _new_client(LINK_CHECK_CONCURRENCY, 15.0, http2=False) as client:

        async def request(url: str, follow: bool) -> httpx.Response:
            resp = await client.head(url, follow_redirects=follow)
            if resp.status_code in {405, 501}:
                resp = await client.get(url, follow_redirects=follow)
            return resp

        async def one(url: str) -> None:
            if not is_safe_external_url(url):
                return
            async with sem:
                try:
                    resp = await request(url, False)
                    status = resp.status_code
                    info: dict[str, Any] = {"status": status, "broken": False, "redirect": False}
                    if 300 <= status < 400:
                        final = await request(url, True)
                        # Alleen een trailing slash of http→https verschil telt niet als redirect.
                        same = url_key(str(final.url)) == url_key(url)
                        info.update({
                            "redirect": not same,
                            "final_url": str(final.url),
                            "status": final.status_code if same else status,
                        })
                        status = final.status_code
                    info["broken"] = status >= 400 and status not in _INCONCLUSIVE_STATUSES
                    out[url_key(url)] = info
                except httpx.HTTPError:
                    return

        await asyncio.gather(*(one(u) for u in todo))
    return out


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_content_scan_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_content_scan_task(self, scan_id: str) -> None:
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None or str(scan.status).lower() in STOPPED_STATUSES:
            return
        source = db.get(LaunchScan, scan.source_scan_id) if scan.source_scan_id else None
        if source is None:
            _update(scan_id, status="failed", error_message="Fase-1 scan niet gevonden.")
            return
        base_url = scan.base_url
        pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == source.id).all()
        targets = [
            {"id": p.id, "url": p.final_url or p.url, "page_type": p.page_type,
             "ahrefs": ahrefs_enrich.keyword_hint(p)}
            for p in pages
            if _is_ok_html(p) and p.indexable is not False
        ]
        ahrefs_enrich.mark_fixed_keywords(t["ahrefs"] for t in targets)
        # Vastgelegde zoekwoorden (handmatig of Ahrefs) meenemen uit de vorige fase-3 scan.
        keywords: dict[str, dict[str, Any]] = {}
        previous = (
            db.query(LaunchScan)
            .filter(LaunchScan.customer_website_id == scan.customer_website_id, LaunchScan.phase == 3,
                    LaunchScan.id != scan.id, LaunchScan.checklist.isnot(None))
            .order_by(LaunchScan.created_at.desc())
            .first()
        )
        if previous is not None:
            for old in db.query(LaunchContentPage).filter(
                LaunchContentPage.scan_id == previous.id,
                LaunchContentPage.focus_keyword.isnot(None),
                LaunchContentPage.keyword_source.notin_(("ai",)),
            ):
                keywords[url_key(old.url)] = {
                    "focus_keyword": old.focus_keyword, "intent": old.intent,
                    "keyword_source": old.keyword_source,
                }

    try:
        # 1. HTML opnieuw ophalen en de inhoud per pagina bewaren
        _update(scan_id, status="fetching", total_urls=len(targets), inventoried_urls=0)
        root_domain = root_domain_of(base_url) or urlparse(base_url).netloc

        def on_batch(done: int) -> bool:
            _update(scan_id, inventoried_urls=done)
            return not _is_stopped(scan_id)

        fetched = asyncio.run(_fetch_content(targets, root_domain, settings.launch_scan_http_concurrency, on_batch))
        if _is_stopped(scan_id):
            return
        failed = len(targets) - len(fetched)
        if failed:
            warnings.append(f"{failed} van de {len(targets)} pagina's konden niet opnieuw worden opgehaald.")
        if not fetched:
            _update(scan_id, status="failed", error_message="Geen enkele pagina kon worden opgehaald.",
                    warnings=warnings)
            return
        now = _now()
        with SessionLocal() as db:
            db.add_all([
                LaunchContentPage(
                    id=str(uuid.uuid4()), scan_id=scan_id, source_page_id=t["id"], url=t["url"],
                    path=_path_of(t["url"]), page_type=t["page_type"], created_at=now,
                    **_with_ahrefs_signal(fetched[t["id"]], t["ahrefs"]),
                    **ahrefs_enrich.choose_keyword(keywords.get(url_key(t["url"])), t["ahrefs"]),
                )
                for t in targets if t["id"] in fetched
            ])
            db.commit()
        _update(scan_id, inventoried_urls=len(targets), failed_urls=failed, warnings=warnings)

        # 2. Interne links op de inhoudspagina's controleren (404's en redirects)
        _update(scan_id, status="linking")
        with SessionLocal() as db:
            rows = content_pages(db, scan_id)
            known_ok = {url_key(p.url) for p in rows}
            link_urls = list(dict.fromkeys(l["url"] for p in rows for l in (p.links or [])))
        link_status = asyncio.run(_check_links(link_urls, known_ok))
        if _is_stopped(scan_id):
            return
        unchecked = len({url_key(u) for u in link_urls if _looks_like_page(u)} - set(link_status))
        if unchecked:
            warnings.append(f"{unchecked} interne links zijn niet gecontroleerd (limiet of geen antwoord).")

        # 3. Regelcontrole, checklist en actiepunten
        _update(scan_id, status="checking")
        with SessionLocal() as db:
            scan = db.get(LaunchScan, scan_id)
            rows = content_pages(db, scan_id)
            payload, page_checks = build_content_payload(db, scan, rows, link_status=link_status)
            states = {
                s.item_key: s.manual_status
                for s in db.query(LaunchChecklistState).filter(
                    LaunchChecklistState.customer_website_id == scan.customer_website_id
                ).all()
            }
            issues = generate_content_issues(rows, page_checks, payload["items"], states)
            carried = previous_issue_state(db, scan)
            now = _now()
            db.add_all([
                LaunchScanIssue(id=str(uuid.uuid4()), scan_id=scan_id, created_at=now, updated_at=now,
                                **with_carried_state(issue, carried))
                for issue in issues
            ])
            db.commit()

        _update(
            scan_id,
            status="completed",
            checklist=payload,
            summary_stats=payload.get("summary"),
            warnings=warnings,
            completed_at=_now(),
        )
    except SoftTimeLimitExceeded:
        _update(scan_id, status="failed", error_message="Scan duurde te lang en is afgebroken.", warnings=warnings)
    except Exception as exc:
        logger.exception("Content-scan %s mislukt", scan_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)


# --- stap 2: AI-analyse -------------------------------------------------------------

def _analysis_active(scan_id: str) -> bool:
    """De analyse loopt zolang de scan op 'analyzing' staat (annuleren zet hem terug)."""
    return _status_of(scan_id) == "analyzing"


def _reset_unfinished(scan_id: str) -> None:
    with SessionLocal() as db:
        reset_unfinished_analysis(db, scan_id)
        db.commit()


def _finish_analysis(scan_id: str, *, warnings: list[str], usage: Usage, **fields: Any) -> None:
    """Checklist herberekenen en de scan weer op 'completed' zetten."""
    _reset_unfinished(scan_id)
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None:
            return
        rebuild_content_checklist(db, scan)
        previous = scan.agent_trace if isinstance(scan.agent_trace, dict) else {}
        total = Usage()
        total.merge(previous.get("analysis_usage") or {})
        total.merge(usage.to_dict())
        trace = {**previous, **(fields.pop("agent_trace", None) or {}), "analysis_usage": total.to_dict()}
        scan.agent_trace = trace
        scan.warnings = [*(scan.warnings or []), *warnings][-50:]
        for key, value in fields.items():
            setattr(scan, key, value)
        if str(scan.status).lower() == "analyzing":
            scan.status = "completed"
        scan.updated_at = _now()
        db.commit()


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_content_analysis_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_content_analysis_task(self, scan_id: str, page_ids: list[str], run_gap_agent: bool = True) -> None:
    warnings: list[str] = []
    usage = Usage()
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None or scan.phase != 3 or str(scan.status).lower() != "analyzing":
            return
        customer = db.get(CustomerWebsite, scan.customer_website_id)
        customer_name = customer.name if customer else scan.base_url
        user_id = scan.created_by
        gap_done = bool((scan.checklist or {}).get("gap_analyzed_at"))

    try:
        # 1. Pagina-agents op de geselecteerde pagina's
        done = 0

        def one(page_id: str) -> dict[str, Any]:
            if not _analysis_active(scan_id):
                return {"ok": False, "warnings": [], "usage": {}, "skipped": True}
            return analyse_page(scan_id, page_id, user_id=user_id, customer_name=customer_name)

        with ThreadPoolExecutor(max_workers=settings.launch_content_ai_concurrency) as pool:
            futures = [pool.submit(one, page_id) for page_id in page_ids]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:  # onverwachte fout in één pagina: de rest gaat door
                    logger.warning("AI-analyse van een pagina mislukt (scan %s): %s", scan_id, exc)
                    warnings.append(f"AI-analyse van een pagina mislukt: {exc}")
                    continue
                usage.merge(result.get("usage") or {})
                warnings.extend(result.get("warnings") or [])
                if not result.get("skipped"):
                    done += 1
                    _update(scan_id, vitals_measured=done)

        if not _analysis_active(scan_id):
            # Geannuleerd: wat klaar is blijft staan.
            _finish_analysis(scan_id, warnings=warnings, usage=usage)
            return

        # 2. Contentgap (nieuwe content) op siteniveau
        _update(scan_id)  # levensteken: de volgende stappen duren enkele minuten
        if run_gap_agent or not gap_done:
            try:
                usage.merge(run_gap(scan_id, user_id=user_id, customer_name=customer_name))
            except Exception as exc:
                logger.warning("Contentgap-agent faalde voor scan %s: %s", scan_id, exc)
                warnings.append(f"Contentgap-analyse niet gelukt: {exc}")

        # 3. Checklist bijwerken zodat het rapport de nieuwe stand ziet
        with SessionLocal() as db:
            scan = db.get(LaunchScan, scan_id)
            rebuild_content_checklist(db, scan)
            db.commit()

        # 4. Rapport
        _update(scan_id)
        fields: dict[str, Any] = {}
        try:
            report = run_report(scan_id, user_id=user_id, customer_name=customer_name)
            usage.add(report)
            if report.output:
                fields["ai_summary"] = report.output
            fields["agent_trace"] = report.to_trace()
        except Exception as exc:
            logger.warning("Rapport-agent faalde voor scan %s: %s", scan_id, exc)
            warnings.append(f"AI-rapport niet gegenereerd: {exc}")

        _finish_analysis(scan_id, warnings=warnings, usage=usage, **fields)
    except SoftTimeLimitExceeded:
        warnings.append("De AI-analyse duurde te lang en is afgebroken; afgeronde pagina's zijn bewaard.")
        _finish_analysis(scan_id, warnings=warnings, usage=usage)
    except Exception as exc:
        logger.exception("AI-analyse %s mislukt", scan_id)
        warnings.append(f"AI-analyse afgebroken: {str(exc)[:300]}")
        _finish_analysis(scan_id, warnings=warnings, usage=usage)
