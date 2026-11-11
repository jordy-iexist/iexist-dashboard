"""Celery-task: livegang fase 2 (GEO/SEO-checklist).

Bouwt voort op een voltooide fase-1 scan: haalt de HTML van de fase-1 pagina's
opnieuw op voor rijkere extractie, bepaalt paginatypes, bouwt de linkgraaf,
test CDN-bottoegang, evalueert de checklist, maakt actiepunten en laat de
GEO-agent een rapport schrijven.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.agents import AGENTS, run_agent
from app.agents.geo.tools import GeoContext
from app.core.config import settings
from app.core.url_guard import is_safe_external_url
from app.db.models import (
    CustomerWebsite,
    LaunchChecklistState,
    LaunchScan,
    LaunchScanIssue,
    LaunchScanPage,
)
from app.db.session import SessionLocal
from app.features.launch_checklist.services.discovery import root_domain_of
from app.features.launch_checklist.services.geo_rebuild import (
    apply_page_types,
    build_checklist_payload,
    collect_extras,
)
from app.features.launch_checklist.services.geo_checks import find_home
from app.features.launch_checklist.services.geo_extract import extract_geo
from app.features.launch_checklist.services.inventory import MAX_BODY_BYTES, _new_client
from app.features.launch_checklist.services.issue_state import (
    previous_issue_state,
    with_carried_state,
)
from app.features.launch_checklist.services.issues import _is_ok_html, generate_geo_issues
from app.features.launch_checklist.services.link_graph import GraphNode, build_link_graph
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}
BATCH_SIZE = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_stopped(scan_id: str) -> bool:
    with SessionLocal() as db:
        row = db.query(LaunchScan.status).filter(LaunchScan.id == scan_id).first()
        return row is None or str(row[0] or "").lower() in STOPPED_STATUSES


def _update(scan_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(LaunchScan).filter(
            LaunchScan.id == scan_id, LaunchScan.status != "canceled"
        ).update(fields, synchronize_session=False)
        db.commit()


async def _refetch(
    targets: list[tuple[str, str]],
    root_domain: str,
    concurrency: int,
    on_batch: Any,
) -> dict[str, dict[str, Any]]:
    """targets: [(page_id, url)] → {page_id: {jsonld, outlinks, signals}}."""
    results: dict[str, dict[str, Any]] = {}
    sem = asyncio.Semaphore(concurrency)

    async with _new_client(concurrency, 20.0) as client, _new_client(concurrency, 20.0, http2=False) as h1:

        async def one(page_id: str, url: str) -> None:
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
            extracted = extract_geo(html, str(resp.url), root_domain)
            results[page_id] = {
                "jsonld": extracted.jsonld,
                "outlinks": extracted.outlinks,
                "signals": extracted.signals,
            }

        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start: start + BATCH_SIZE]
            await asyncio.gather(*(one(pid, url) for pid, url in batch))
            if not on_batch(start + len(batch)):
                break
    return results


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_geo_scan_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_geo_scan_task(self, scan_id: str) -> None:
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None or str(scan.status).lower() in STOPPED_STATUSES:
            return
        source = db.get(LaunchScan, scan.source_scan_id) if scan.source_scan_id else None
        if source is None:
            _update(scan_id, status="failed", error_message="Fase-1 scan niet gevonden.")
            return
        customer = db.get(CustomerWebsite, scan.customer_website_id)
        customer_name = customer.name if customer else scan.base_url
        customer_id = scan.customer_website_id
        base_url = scan.base_url
        source_id = source.id
        user_id = scan.created_by
        pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == source_id).all()
        targets = [(p.id, p.final_url or p.url) for p in pages if _is_ok_html(p)]

    try:
        # 1. HTML opnieuw ophalen voor rijkere extractie
        _update(scan_id, status="fetching", total_urls=len(targets), inventoried_urls=0)
        root_domain = root_domain_of(base_url) or urlparse(base_url).netloc

        def on_batch(done: int) -> bool:
            _update(scan_id, inventoried_urls=done)
            return not _is_stopped(scan_id)

        fetched = asyncio.run(_refetch(targets, root_domain, settings.launch_scan_http_concurrency, on_batch))
        if _is_stopped(scan_id):
            return
        failed = len(targets) - len(fetched)
        if failed:
            warnings.append(f"{failed} van de {len(targets)} pagina's konden niet opnieuw worden opgehaald.")
        with SessionLocal() as db:
            for page_id, data in fetched.items():
                db.query(LaunchScanPage).filter(LaunchScanPage.id == page_id).update(data, synchronize_session=False)
            db.commit()
        _update(scan_id, inventoried_urls=len(targets), failed_urls=failed, warnings=warnings)

        # 2. Paginatypes + linkgraaf
        _update(scan_id, status="linking")
        with SessionLocal() as db:
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == source_id).all()
            apply_page_types(db, pages, customer_id=customer_id, base_url=base_url, user_id=user_id)
            home = find_home(pages)
            graph = build_link_graph(
                [GraphNode(p.id, p.url, p.final_url, p.outlinks if p.id in fetched else None) for p in pages],
                home.id if home is not None else None,
            )
            for p in pages:
                p.click_depth = graph.depth.get(p.id)
                p.inlinks = graph.inlinks.get(p.id, 0)
            db.commit()
        if _is_stopped(scan_id):
            return

        # 3. Extra checks (sitemap_index, HTML-sitemap, CDN-bottoegang) + evaluatie
        _update(scan_id, status="checking")
        with SessionLocal() as db:
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == source_id).all()
            extras = collect_extras(base_url, pages)
            scan = db.get(LaunchScan, scan_id)
            payload = build_checklist_payload(db, scan, pages, extras)
            states = {
                s.item_key: s.manual_status
                for s in db.query(LaunchChecklistState).filter(
                    LaunchChecklistState.customer_website_id == scan.customer_website_id
                ).all()
            }
            issues = generate_geo_issues(payload["items"], states)
            carried = previous_issue_state(db, scan)
            now = _now()
            db.add_all([
                LaunchScanIssue(id=str(uuid.uuid4()), scan_id=scan_id,
                                created_at=now, updated_at=now,
                                **with_carried_state(issue, carried))
                for issue in issues
            ])
            db.commit()
        _update(scan_id, status="analyzing", checklist=payload, summary_stats=payload.get("summary"))

        # 4. GEO-agent schrijft het rapport
        ai_summary: str | None = None
        agent_trace: dict[str, Any] | None = None
        try:
            with SessionLocal() as db:
                result = run_agent(
                    AGENTS["geo"](),
                    user_id=user_id,
                    input=f"Schrijf het GEO/SEO-rapport (fase 2) voor {customer_name} ({base_url}).",
                    context=GeoContext(db=db, scan_id=scan_id, source_scan_id=source_id, customer_name=customer_name),
                )
                ai_summary = result.output or None
                agent_trace = result.to_trace()
        except Exception as exc:  # geen key / API-fout: checklist zelf is wel klaar
            logger.warning("GEO-agent faalde voor scan %s: %s", scan_id, exc)
            warnings.append(f"AI-rapport niet gegenereerd: {exc}")
            agent_trace = {"error": str(exc)}

        _update(
            scan_id,
            status="completed",
            ai_summary=ai_summary,
            agent_trace=agent_trace,
            warnings=warnings,
            completed_at=_now(),
        )
    except SoftTimeLimitExceeded:
        _update(scan_id, status="failed", error_message="Scan duurde te lang en is afgebroken.", warnings=warnings)
    except Exception as exc:
        logger.exception("GEO-scan %s mislukt", scan_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)

