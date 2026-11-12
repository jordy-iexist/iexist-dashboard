"""Celery-task: livegang fase 4 (Kwartaal GEO-werkzaamheden).

Herhaalt de nulmeting met eigen pagina's (crawl, AI-checks, Ahrefs), haalt de
HTML opnieuw op voor JSON-LD en schema-validatie, haalt Search Console-data op
(prestaties, sitemaps, indexstatus van nieuwe pagina's), vergelijkt alles met de
vorige ronde (of de nulmeting), evalueert de fase-4 checklist, maakt
actiepunten en laat een agent een conceptrapport schrijven.

De fase-1 scan blijft onaangeroerd, dus fase 2 en 3 worden niet 'verouderd'.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.agents import AGENTS, run_agent
from app.agents.quarterly_report.tools import QuarterlyContext
from app.core.config import settings
from app.core.url_guard import is_safe_external_url
from app.db.models import CustomerWebsite, LaunchScan, LaunchScanIssue, LaunchScanPage
from app.db.session import SessionLocal
from app.features.launch_checklist.services.ai_checks import run_ai_checks
from app.features.launch_checklist.services.checklist_view import (
    comparison_base,
    states_for_customer,
)
from app.features.launch_checklist.services.discovery import discover_from_sitemaps, root_domain_of
from app.features.launch_checklist.services.geo_extract import extract_geo
from app.features.launch_checklist.services import gsc_enrich
from app.features.launch_checklist.services.geo_rebuild import apply_page_types
from app.features.launch_checklist.services.inventory import (
    MAX_BODY_BYTES,
    PageRecord,
    _new_client,
    run_inventory,
)
from app.features.launch_checklist.services.issue_state import (
    previous_issue_state,
    with_carried_state,
)
from app.features.launch_checklist.services.issues import (
    _is_ok_html,
    generate_issues,
    generate_quarterly_issues,
)
from app.features.launch_checklist.services.quarterly_checks import (
    evaluate_ai_scan,
    evaluate_new_pages,
    evaluate_report,
    evaluate_schema,
    evaluate_search_console,
)
from app.features.launch_checklist.services.quarterly_compare import (
    base_info,
    compare_ahrefs,
    compare_ai,
    compare_issues,
    compare_pages,
    compare_rankings,
    compare_search_console,
    count_issue_types,
    is_working,
    lost_schema_types,
    page_key,
)
from app.features.launch_checklist.services.quarterly_checklist import period_label
from app.features.launch_checklist.services.schema_validate import validate_html
from app.features.launch_checklist.services.stats import build_summary_stats
from app.features.launch_checklist.worker.launch_scan import _enrich_with_ahrefs, _record_to_row
from app.services.search_console import client as gsc_client
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

STOPPED_STATUSES = {"canceled", "deleted"}
BATCH_SIZE = 20
NEW_PAGES_IN_COMPARISON = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_stopped(scan_id: str) -> bool:
    with SessionLocal() as db:
        row = db.query(LaunchScan.status).filter(LaunchScan.id == scan_id).first()
        return row is None or str(row[0] or "").lower() in STOPPED_STATUSES


def _update(scan_id: str, **fields: Any) -> None:
    """Werk de scan bij, behalve als hij inmiddels geannuleerd is."""
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
    """targets: [(page_id, url)] → {page_id: {jsonld, outlinks, signals}}.

    Zoals fase 2, plus de schema-validatie op de ruwe JSON-LD in
    `signals["schema_validation"]`.
    """
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
            signals = dict(extracted.signals)
            signals["schema_validation"] = validate_html(html)
            results[page_id] = {
                "jsonld": extracted.jsonld,
                "outlinks": extracted.outlinks,
                "signals": signals,
            }

        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start: start + BATCH_SIZE]
            await asyncio.gather(*(one(pid, url) for pid, url in batch))
            if not on_batch(start + len(batch)):
                break
    return results


def _copy_page_types(base_pages: list[LaunchScanPage], pages: list[LaunchScanPage]) -> None:
    """Neem paginatypes over van de basis, zodat alleen nieuwe pagina's opnieuw bepaald worden."""
    known = {page_key(p): p for p in base_pages if p.page_type}
    for page in pages:
        before = known.get(page_key(page))
        if before is not None:
            page.page_type, page.page_type_source = before.page_type, before.page_type_source


def _inspection_urls(scan_id: str, base_url: str) -> list[str]:
    """URL's voor de URL-inspectie: de homepage en nieuwe, werkende, indexeerbare pagina's."""
    limit = settings.gsc_inspect_max_urls
    if limit <= 0:
        return []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None:
            return []
        pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).all()
        base = comparison_base(db, scan)
        base_pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == base.id).all() if base else []
        new_pages = compare_pages(base_pages, pages)["new"] if base else []
        candidates = [base_url] + [
            p.final_url or p.url for p in new_pages if is_working(p) and p.indexable is not False
        ]
    urls: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        key = url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            urls.append(url)
    return urls[:limit]


def _enrich_with_search_console(
    scan_id: str, manual_property: str | None, base_url: str, warnings: list[str]
) -> dict[str, Any] | None:
    """Search Console-snapshot van de klant-property, of None zonder koppeling of data."""
    if not gsc_client.is_configured():
        warnings.append(
            "Search Console is niet gekoppeld (GSC_CLIENT_ID, GSC_CLIENT_SECRET, GSC_REFRESH_TOKEN): "
            "geen klikken, vertoningen en indexstatus."
        )
        return None
    service = gsc_client.get_service()
    sites = [] if (manual_property or "").strip() else gsc_client.list_sites(service=service)
    site_url, source = gsc_enrich.resolve_property(manual_property, base_url, sites)
    if not site_url:
        warnings.append(
            f"Geen Search Console-property gevonden voor {urlparse(base_url).netloc}: kies de property bij "
            "fase 4 of geef het Google-account toegang."
        )
        return None
    snapshot = gsc_enrich.fetch_snapshot(site_url, source, service=service)
    warnings.extend(f"Search Console: {error}" for error in snapshot["errors"])
    if not gsc_enrich.has_data(snapshot):
        return None
    if _is_stopped(scan_id):
        return snapshot
    urls = _inspection_urls(scan_id, base_url)
    if urls:
        inspection = gsc_enrich.inspect_pages(
            site_url, urls, service=service, should_continue=lambda: not _is_stopped(scan_id)
        )
        snapshot["inspection"] = inspection
        if inspection["errors"]:
            warnings.append(
                f"Search Console: {len(urls) - inspection['checked']} van de {len(urls)} URL-inspecties "
                f"zijn niet gelukt ({inspection['errors'][0]})."
            )
    return snapshot


def _comparison_payload(
    *,
    base: LaunchScan | None,
    base_issue_types: list[str],
    pages_diff: dict[str, Any],
    ai_checks: dict[str, Any],
    issue_types: list[str],
    ahrefs_after: dict[str, Any] | None,
    rankings: dict[str, Any] | None,
    search_console: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "base": base_info(base) if base is not None else None,
        "ai": compare_ai(base.ai_checks if base else None, ai_checks),
        "issues": compare_issues(count_issue_types(base_issue_types), count_issue_types(issue_types)),
        "pages": {
            "before": pages_diff["before"],
            "after": pages_diff["after"],
            "new": len(pages_diff["new"]),
            "removed": len(pages_diff["removed"]),
            "broken": len(pages_diff["broken"]),
            "new_examples": [p.url for p in pages_diff["new"]][:NEW_PAGES_IN_COMPARISON],
        },
        "ahrefs": compare_ahrefs(base.ahrefs if base else None, ahrefs_after),
        "rankings": rankings,
        "search_console": compare_search_console(search_console),
    }


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_quarterly_scan_task",
    soft_time_limit=3300,
    time_limit=3600,
)
def run_quarterly_scan_task(self, scan_id: str) -> None:
    warnings: list[str] = []
    with SessionLocal() as db:
        scan = db.get(LaunchScan, scan_id)
        if scan is None or str(scan.status).lower() in STOPPED_STATUSES:
            logger.info("Fase 4-scan %s niet gevonden of geannuleerd.", scan_id)
            return
        customer = db.get(CustomerWebsite, scan.customer_website_id)
        customer_id = scan.customer_website_id
        customer_name = customer.name if customer else scan.base_url
        gsc_property = customer.gsc_property if customer else None
        base_url = scan.base_url
        max_pages = int(scan.max_pages or 500)
        user_id = scan.created_by
        period = scan.period or ""

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

        # 2. Inventaris, AI-checks en Ahrefs (zoals de nulmeting, zonder Core Web Vitals)
        progress = {"done": 0, "failed": 0}

        def on_inventory(batch: list[PageRecord]) -> bool:
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
                on_batch=on_inventory,
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

        ai_checks = run_ai_checks(
            base_url=base_url,
            robots_txt=discovery.robots_txt,
            robots_status=discovery.robots_status,
            sitemaps=discovery.sitemaps,
            records=records,
        )
        ahrefs_summary: dict[str, Any] | None = None
        try:
            ahrefs_summary = _enrich_with_ahrefs(scan_id, records, warnings)
        except Exception as exc:  # Ahrefs is een verrijking: de scan gaat zonder door
            logger.warning("Ahrefs-verrijking faalde voor fase 4-scan %s: %s", scan_id, exc)
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

        # 3. HTML opnieuw ophalen: JSON-LD, signalen en schema-validatie
        with SessionLocal() as db:
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).all()
            targets = [(p.id, p.final_url or p.url) for p in pages if _is_ok_html(p)]
        _update(scan_id, status="fetching", total_urls=len(targets), inventoried_urls=0)
        root_domain = root_domain_of(base_url) or urlparse(base_url).netloc

        def on_fetch(done: int) -> bool:
            _update(scan_id, inventoried_urls=done)
            return not _is_stopped(scan_id)

        fetched = asyncio.run(_refetch(targets, root_domain, settings.launch_scan_http_concurrency, on_fetch))
        if _is_stopped(scan_id):
            return
        if len(fetched) < len(targets):
            warnings.append(
                f"{len(targets) - len(fetched)} van de {len(targets)} pagina's konden niet opnieuw worden "
                "opgehaald voor de schema-validatie."
            )
        with SessionLocal() as db:
            for page_id, data in fetched.items():
                db.query(LaunchScanPage).filter(LaunchScanPage.id == page_id).update(data, synchronize_session=False)
            db.commit()
        _update(scan_id, total_urls=len(records), inventoried_urls=len(records), warnings=warnings)

        # 3b. Search Console: prestaties, sitemaps en indexstatus van nieuwe pagina's
        gsc_snapshot: dict[str, Any] | None = None
        try:
            gsc_snapshot = _enrich_with_search_console(scan_id, gsc_property, base_url, warnings)
        except Exception as exc:  # Search Console is een verrijking: de scan gaat zonder door
            logger.warning("Search Console-verrijking faalde voor fase 4-scan %s: %s", scan_id, exc)
            warnings.append(f"Search Console-data niet opgehaald: {exc}")
        if _is_stopped(scan_id):
            return
        if gsc_snapshot is not None:
            _update(scan_id, search_console=gsc_snapshot, warnings=warnings)

        # 4. Vergelijken, checklist en actiepunten
        _update(scan_id, status="checking")
        with SessionLocal() as db:
            scan = db.get(LaunchScan, scan_id)
            pages = db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == scan_id).all()
            base = comparison_base(db, scan)
            base_pages = (
                db.query(LaunchScanPage).filter(LaunchScanPage.scan_id == base.id).all() if base else []
            )
            base_issue_types = (
                [row[0] for row in db.query(LaunchScanIssue.issue_type).filter(LaunchScanIssue.scan_id == base.id)]
                if base else []
            )
            if base is None:
                warnings.append("Geen eerdere scan gevonden om mee te vergelijken.")

            _copy_page_types(base_pages, pages)
            apply_page_types(db, pages, customer_id=customer_id, base_url=base_url, user_id=user_id)

            base_label = base_info(base)["label"] if base else "de vorige meting"
            pages_diff = compare_pages(base_pages, pages)
            page_issues = generate_issues(pages, ai_checks)
            rankings = compare_rankings(db, customer_id, base.completed_at if base else None)
            comparison = _comparison_payload(
                base=base,
                base_issue_types=base_issue_types,
                pages_diff=pages_diff,
                ai_checks=ai_checks,
                issue_types=[i["issue_type"] for i in page_issues],
                ahrefs_after=ahrefs_summary,
                rankings=rankings,
                search_console=gsc_snapshot,
            )
            items = {
                "c4_ai_scan": evaluate_ai_scan(comparison["ai"], base_label),
                "c4_new_pages": evaluate_new_pages(
                    pages_diff, source, base_label, (gsc_snapshot or {}).get("inspection")
                ),
                "c4_schema_validation": evaluate_schema(pages, lost_schema_types(base_pages, pages)),
            }
            # Zonder koppeling blijft het Search Console-punt volledig handmatig.
            if comparison["search_console"] is not None:
                items["c4_search_console"] = evaluate_search_console(
                    comparison["search_console"], settings.gsc_clicks_drop_warn_pct
                )
            states = {k: s.manual_status for k, s in states_for_customer(db, customer_id, period).items()}
            issues = page_issues + generate_quarterly_issues(items, states)
            carried = previous_issue_state(db, scan)
            now = _now()
            db.add_all([
                LaunchScanIssue(id=str(uuid.uuid4()), scan_id=scan_id,
                                created_at=now, updated_at=now,
                                **with_carried_state(issue, carried))
                for issue in issues
            ])
            stats = build_summary_stats(pages, issues)
            db.commit()

        payload: dict[str, Any] = {
            "period": period,
            "period_label": period_label(period),
            "items": items,
            "comparison": comparison,
            # Welke bronnen deze ronde gevuld zijn. GA4 en Bing volgen later.
            "sources": {
                "ahrefs": bool(ahrefs_summary and ahrefs_summary.get("domain")),
                "seo_tracker": rankings is not None,
                "search_console": comparison["search_console"] is not None,
                "ga4": None,
                "bing_webmaster": None,
            },
            "generated_at": _now().isoformat(),
            "summary": {
                "auto_status": dict(Counter(r.get("status") for r in items.values())),
                "pages": pages_diff["after"],
                "new_pages": len(pages_diff["new"]),
                "broken_pages": len(pages_diff["broken"]),
            },
        }
        _update(scan_id, status="analyzing", checklist=payload, summary_stats=stats, warnings=warnings)

        # 5. Agent schrijft het conceptrapport
        ai_summary: str | None = None
        agent_trace: dict[str, Any] | None = None
        try:
            with SessionLocal() as db:
                result = run_agent(
                    AGENTS["quarterly_report"](),
                    user_id=user_id,
                    input=(
                        f"Schrijf het conceptrapport (fase 4, ronde {period_label(period)}) voor "
                        f"{customer_name} ({base_url})."
                    ),
                    context=QuarterlyContext(db=db, scan_id=scan_id, customer_name=customer_name, period=period),
                )
                ai_summary = result.output or None
                agent_trace = result.to_trace()
        except Exception as exc:  # geen key / API-fout: de checklist zelf is wel klaar
            logger.warning("Kwartaalrapport-agent faalde voor scan %s: %s", scan_id, exc)
            warnings.append(f"Conceptrapport niet gegenereerd: {exc}")
            agent_trace = {"error": str(exc)}

        payload["items"]["c4_monthly_report"] = evaluate_report(
            bool(ai_summary), bool(payload["sources"]["search_console"])
        )
        payload["summary"]["auto_status"] = dict(Counter(r.get("status") for r in payload["items"].values()))
        _update(
            scan_id,
            status="completed",
            checklist=payload,
            ai_summary=ai_summary,
            agent_trace=agent_trace,
            warnings=warnings,
            completed_at=_now(),
        )
    except SoftTimeLimitExceeded:
        _update(scan_id, status="failed", error_message="Scan duurde te lang en is afgebroken.", warnings=warnings)
    except Exception as exc:
        logger.exception("Fase 4-scan %s mislukt", scan_id)
        _update(scan_id, status="failed", error_message=str(exc)[:1000], warnings=warnings)
