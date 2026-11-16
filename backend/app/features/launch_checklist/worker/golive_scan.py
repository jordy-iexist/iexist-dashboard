"""Celery-task: livegangscan (fase 5) voor de oplevering van een nieuwe website.

Staat los van de SEO/GEO-scan: werkt op het live domein, ook voor een klant
zonder nulmeting. Volledige inventaris tot `max_pages` (restanten van een
testomgeving staan op willekeurige pagina's, een steekproef mist ze), met de
livegang-signalen per pagina via de `page_hook`, daarna een handvol probes en
de evaluatie. Geen PageSpeed, Ahrefs, AI-agent of actiepunten: de bevindingen
staan in `scan.checklist["items"]`.

Statussen: discovering → inventory → checking → completed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.core.config import settings
from app.db.models import LaunchScan
from app.db.session import SessionLocal
from app.features.launch_checklist.services.discovery import discover_from_sitemaps
from app.features.launch_checklist.services.golive_checks import blocked_ratio, build_golive_payload
from app.features.launch_checklist.services.golive_extract import GoLiveSite, make_page_hook
from app.features.launch_checklist.services.golive_probes import run_probes
from app.features.launch_checklist.services.inventory import PageRecord, run_inventory
from app.features.launch_checklist.services.scan_recovery import heartbeat
from app.features.launch_checklist.worker.launch_scan import _record_to_row
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_status(scan_id: str) -> str:
    with SessionLocal() as db:
        row = db.query(LaunchScan.status).filter(LaunchScan.id == scan_id).first()
        return "deleted" if row is None else str(row[0] or "").lower()


def _is_stopped(scan_id: str) -> bool:
    return _current_status(scan_id) in STOPPED_STATUSES


def _update(scan_id: str, **fields: Any) -> None:
    """Werk de scan bij, behalve als hij inmiddels geannuleerd is."""
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(LaunchScan).filter(
            LaunchScan.id == scan_id, LaunchScan.status != "canceled"
        ).update(fields, synchronize_session=False)
        db.commit()


def _home_icons(records: list[PageRecord]) -> list[str]:
    """Favicon-links van de homepage (uit de livegang-signalen)."""
    for rec in records:
        signals = rec.extra.get("golive") if rec.extra else None
        if not isinstance(signals, dict):
            continue
        parsed = urlparse(rec.final_url or rec.url)
        if parsed.path in ("", "/") and not parsed.query:
            return list(signals.get("icons") or [])
    return []


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_golive_scan_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_golive_scan_task(self, scan_id: str) -> None:
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        # 'failed' vóór de start: de scan is als vastgelopen hersteld terwijl de taak nog in de
        # wachtrij stond (scan_recovery); dan niet alsnog beginnen.
        if scan is None or str(scan.status).lower() in STOPPED_STATUSES | {"failed"}:
            logger.info("Livegangscan %s niet gevonden of geannuleerd.", scan_id)
            return
        base_url = scan.base_url
        max_pages = int(scan.max_pages or 500)

    try:
        site = GoLiveSite.from_base_url(base_url, settings.launch_golive_test_domain_list)

        # 1. Discovery
        _update(scan_id, status="discovering")
        discovery = discover_from_sitemaps(
            base_url, max_urls=max_pages, on_progress=heartbeat(lambda: _update(scan_id))
        )
        if discovery.urls:
            source, seeds, follow = "sitemap", discovery.urls, False
            if discovery.skipped_due_to_limit:
                warnings.append(
                    f"Sitemap bevat {discovery.skipped_due_to_limit} URL's meer dan het maximum van {max_pages}."
                )
        else:
            source, seeds, follow = "crawl", [base_url], True
            warnings.append("Geen sitemap gevonden: pagina's zijn gevonden door de site te crawlen.")
        _update(
            scan_id,
            status="inventory",
            discovery_source=source,
            total_urls=len(seeds) if not follow else 0,
            warnings=warnings,
        )
        if _is_stopped(scan_id):
            return

        # 2. Inventaris met de livegang-signalen per pagina (geen tweede verzoek)
        progress = {"done": 0, "failed": 0}

        def on_batch(batch: list[PageRecord]) -> bool:
            progress["done"] += len(batch)
            progress["failed"] += len([r for r in batch if r.error])
            _update(scan_id, inventoried_urls=progress["done"], failed_urls=progress["failed"])
            return not _is_stopped(scan_id)

        records = asyncio.run(
            run_inventory(
                seed_urls=seeds,
                in_sitemap=(source == "sitemap"),
                follow_links=follow,
                max_pages=max_pages,
                concurrency=settings.launch_scan_http_concurrency,
                on_batch=on_batch,
                on_progress=heartbeat(lambda: _update(scan_id)),
                page_hook=make_page_hook(site),
            )
        )
        if _is_stopped(scan_id):
            return
        blocked, total = blocked_ratio(records)
        if total and blocked * 2 > total:
            warnings.append(
                f"{blocked} van de {total} pagina's gaven 401/403/429/503: de scanner "
                "wordt waarschijnlijk geblokkeerd door een firewall of bot-protectie."
            )
        with SessionLocal() as db:
            db.add_all([_record_to_row(scan_id, r) for r in records])
            db.commit()
        _update(
            scan_id,
            status="checking",
            total_urls=len(records),
            inventoried_urls=len(records),
            warnings=warnings,
        )

        # 3. Probes (hostmatrix, certificaat, 404, favicon) en de evaluatie
        probes = run_probes(site, icon_links=_home_icons(records), on_progress=heartbeat(lambda: _update(scan_id)))
        if _is_stopped(scan_id):
            return
        payload = build_golive_payload(
            base_url=base_url, site=site, records=records, discovery=discovery, probes=probes
        )
        _update(
            scan_id,
            status="completed",
            checklist=payload,
            summary_stats=payload["summary"],
            warnings=warnings,
            completed_at=_now(),
        )
    except SoftTimeLimitExceeded:
        _update(scan_id, status="failed", error_message="Scan duurde te lang en is afgebroken.", warnings=warnings)
    except Exception as exc:
        logger.exception("Livegangscan %s mislukt", scan_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)
