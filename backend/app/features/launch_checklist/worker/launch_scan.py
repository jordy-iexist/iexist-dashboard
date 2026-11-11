"""Celery-task: livegang fase 1 (Nulmeting & AI scan)."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.agents import AGENTS, run_agent
from app.agents.nulmeting.tools import NulmetingContext
from app.core.config import settings
from app.db.models import CustomerWebsite, LaunchScan, LaunchScanIssue, LaunchScanPage
from app.db.session import SessionLocal
from app.features.launch_checklist.services import ahrefs_enrich
from app.features.launch_checklist.services.ai_checks import run_ai_checks
from app.features.launch_checklist.services.discovery import discover_from_sitemaps, url_key
from app.features.launch_checklist.services.inventory import PageRecord, run_inventory
from app.features.launch_checklist.services.issue_state import (
    previous_issue_state,
    with_carried_state,
)
from app.features.launch_checklist.services.issues import generate_issues
from app.features.launch_checklist.services.pagespeed import measure_vitals
from app.features.launch_checklist.services.stats import build_summary_stats
from app.services.ahrefs import is_configured as ahrefs_is_configured
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}
_PAGE_FIELDS = {c.key for c in LaunchScanPage.__table__.columns} - {"id", "scan_id", "created_at"}


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


def _record_to_row(scan_id: str, rec: PageRecord) -> LaunchScanPage:
    data = {k: v for k, v in asdict(rec).items() if k in _PAGE_FIELDS}
    return LaunchScanPage(id=str(uuid.uuid4()), scan_id=scan_id, **data)


def _enrich_with_ahrefs(scan_id: str, records: list[PageRecord], warnings: list[str]) -> dict[str, Any] | None:
    """Zet verkeer en backlinks uit Ahrefs op de records en haal onbekende URL's op.

    URL's die Ahrefs kent maar de crawl niet vond (oude of gewijzigde URL's)
    worden aan `records` toegevoegd, zodat een 404 daarop een actiepunt wordt.
    """
    if not ahrefs_is_configured():
        warnings.append("AHREFS_API_KEY ontbreekt: geen verkeers- en backlinkdata uit Ahrefs.")
        return None
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None:
            return None
        snapshot = ahrefs_enrich.load_snapshot(db, scan)
    warnings.extend(f"Ahrefs: {error}" for error in snapshot.errors)

    unknown = ahrefs_enrich.merge_into_records(records, snapshot)
    if unknown and not _is_stopped(scan_id):
        extra = asyncio.run(
            run_inventory(
                seed_urls=unknown,
                in_sitemap=False,
                follow_links=False,
                max_pages=len(unknown),
                concurrency=settings.launch_scan_http_concurrency,
                on_batch=lambda _batch: not _is_stopped(scan_id),
            )
        )
        ahrefs_enrich.mark_extra_records(extra, snapshot)
        records.extend(extra)
    return ahrefs_enrich.scan_summary(snapshot, records)


def _vitals_candidates(pages: list[LaunchScanPage], base_url: str, limit: int) -> list[LaunchScanPage]:
    candidates = [
        p for p in pages
        if p.indexable is True and p.status_code == 200 and not p.redirect_chain
        and "html" in (p.content_type or "").lower()
    ]
    home_key = url_key(base_url.rstrip("/") + "/")
    # Homepage eerst, daarna ondiepe (belangrijkere) pagina's.
    candidates.sort(key=lambda p: (url_key(p.url) != home_key, p.path.count("/"), len(p.path)))
    return candidates[:limit]


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_launch_scan_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_launch_scan_task(self, scan_id: str) -> None:
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None or str(scan.status).lower() in STOPPED_STATUSES:
            logger.info("Launch scan %s niet gevonden of geannuleerd.", scan_id)
            return
        customer = db.get(CustomerWebsite, scan.customer_website_id)
        base_url = scan.base_url
        max_pages = int(scan.max_pages or 500)
        vitals_max = int(scan.vitals_max_pages or 0)
        user_id = scan.created_by
        customer_name = customer.name if customer else base_url

    try:
        # 1. Discovery
        _update(scan_id, status="discovering")
        discovery = discover_from_sitemaps(base_url, max_urls=max_pages)
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

        # 2. Inventaris
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
            )
        )
        if _is_stopped(scan_id):
            return
        blocked = [r for r in records if r.final_status in {401, 403, 429, 503}]
        if records and len(blocked) / len(records) > 0.5:
            warnings.append(
                f"{len(blocked)} van de {len(records)} pagina's gaven 401/403/429/503: de scanner "
                "wordt waarschijnlijk geblokkeerd door een firewall of bot-protectie."
            )

        # 3. AI-checks (gebruikt de in-memory records van de eigen crawl)
        ai_checks = run_ai_checks(
            base_url=base_url,
            robots_txt=discovery.robots_txt,
            robots_status=discovery.robots_status,
            sitemaps=discovery.sitemaps,
            records=records,
        )

        # 3b. Ahrefs: verkeer en backlinks per URL, plus URL's die de crawl niet vond.
        # Na de AI-checks, zodat die extra URL's de schema-dekking niet vertekenen.
        ahrefs_summary: dict[str, Any] | None = None
        try:
            ahrefs_summary = _enrich_with_ahrefs(scan_id, records, warnings)
        except Exception as exc:  # Ahrefs is een verrijking: de scan gaat zonder door
            logger.warning("Ahrefs-verrijking faalde voor scan %s: %s", scan_id, exc)
            warnings.append(f"Ahrefs-data niet opgehaald: {exc}")
        if _is_stopped(scan_id):
            return

        with SessionLocal() as db:
            db.add_all([_record_to_row(scan_id, r) for r in records])
            db.commit()
        _update(
            scan_id,
            total_urls=len(records),
            inventoried_urls=len(records),
            ai_checks=ai_checks,
            warnings=warnings,
            **({"ahrefs": ahrefs_summary} if ahrefs_summary is not None else {}),
        )

        # 4. Core Web Vitals via PSI
        with SessionLocal() as db:
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).all()
            candidates = [(p.id, p.url) for p in _vitals_candidates(pages, base_url, vitals_max)]

        api_key = str(settings.pagespeed_api_key or "").strip()
        if not candidates:
            pass
        elif not api_key:
            warnings.append("PAGESPEED_API_KEY ontbreekt: Core Web Vitals zijn niet gemeten.")
            _update(scan_id, warnings=warnings)
        else:
            _update(scan_id, status="vitals", vitals_total=len(candidates))
            id_by_url = {url: pid for pid, url in candidates}
            vitals_state = {"measured": 0, "failed": 0}

            def on_result(url: str, data: dict[str, Any] | None, error: str | None) -> bool:
                with SessionLocal() as db:
                    values: dict[str, Any] = (
                        {"cwv": data, "cwv_status": data.get("status")}
                        if data else {"cwv": {"error": error}, "cwv_status": None}
                    )
                    db.query(LaunchScanPage).filter(LaunchScanPage.id == id_by_url[url]).update(
                        values, synchronize_session=False
                    )
                    db.commit()
                vitals_state["measured"] += 1
                if not data:
                    vitals_state["failed"] += 1
                _update(scan_id, vitals_measured=vitals_state["measured"])
                return not _is_stopped(scan_id)

            asyncio.run(
                measure_vitals(
                    [url for _, url in candidates],
                    api_key=api_key,
                    concurrency=settings.launch_scan_psi_concurrency,
                    on_result=on_result,
                )
            )
            if vitals_state["failed"]:
                warnings.append(f"{vitals_state['failed']} CWV-meting(en) mislukt (zie per pagina).")
                _update(scan_id, warnings=warnings)
            if _is_stopped(scan_id):
                return

        # 5. Actiepunten + kerncijfers
        with SessionLocal() as db:
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).all()
            issues = generate_issues(pages, ai_checks)
            carried = previous_issue_state(db, db.get(LaunchScan, scan_id))
            now = _now()
            db.add_all([
                LaunchScanIssue(id=str(uuid.uuid4()), scan_id=scan_id,
                                created_at=now, updated_at=now,
                                **with_carried_state(issue, carried))
                for issue in issues
            ])
            stats = build_summary_stats(pages, issues)
            db.commit()
        _update(scan_id, status="analyzing", summary_stats=stats)

        # 6. Nulmeting-agent schrijft het rapport
        ai_summary: str | None = None
        agent_trace: dict[str, Any] | None = None
        try:
            with SessionLocal() as db:
                agent = AGENTS["nulmeting"]()
                result = run_agent(
                    agent,
                    user_id=user_id,
                    input=f"Schrijf de nulmeting voor {customer_name} ({base_url}).",
                    context=NulmetingContext(db=db, scan_id=scan_id, customer_name=customer_name),
                )
                ai_summary = result.output or None
                agent_trace = result.to_trace()
        except Exception as exc:  # geen key / API-fout: scan zelf is wel klaar
            logger.warning("Nulmeting-agent faalde voor scan %s: %s", scan_id, exc)
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
        logger.exception("Launch scan %s mislukt", scan_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)
