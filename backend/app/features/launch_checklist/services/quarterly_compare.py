"""Vergelijking van een fase 4-scan met de vorige ronde (of de nulmeting).

Pure functies op pagina's, AI-checks, actiepunten en Ahrefs-cijfers, plus de
posities uit de SEO-tracker. Het resultaat wordt in de scan bewaard
(`checklist["comparison"]`), zodat het ook leesbaar blijft als de basis-scan
later verwijderd wordt.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.models import LaunchScan, SerpScanResult
from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.issues import ISSUE_TYPES, final_status, issue_type_since
from app.features.launch_checklist.services.quarterly_checklist import KEY_PREFIX, period_label

# Statussen waarbij de scanner waarschijnlijk geblokkeerd werd: geen oordeel.
INCONCLUSIVE_STATUSES = {401, 403, 429, 503}
MAX_LIST = 200
MAX_RANKINGS = 100
# Rich-results-meldingen per URL (een productpagina kan er tientallen hebben).
MAX_RICH_ISSUES_PER_URL = 10

_AI_RANK = {"ok": 0, "warning": 1, "error": 2}

AHREFS_METRICS: list[tuple[str, str]] = [
    ("domain_rating", "Domain Rating"),
    ("refdomains", "Verwijzende domeinen"),
    ("backlinks", "Backlinks"),
    ("org_traffic", "Organisch verkeer / maand"),
    ("org_keywords", "Organische zoekwoorden"),
    ("org_keywords_1_3", "Zoekwoorden in top 3"),
]


# --- pagina's -----------------------------------------------------------------

def page_key(page: Any) -> str:
    return url_key(page.url)


def is_crawled(page: Any) -> bool:
    """Gevonden door de crawl (niet alleen bekend bij Ahrefs)."""
    data = page.ahrefs if isinstance(page.ahrefs, dict) else {}
    return data.get("source") != "ahrefs"


def is_broken(page: Any) -> bool:
    status = final_status(page)
    if status is None:
        return bool(page.error)
    return status >= 400 and status not in INCONCLUSIVE_STATUSES


def is_working(page: Any) -> bool:
    status = final_status(page)
    return status is not None and status < 400


def compare_pages(base_pages: list[Any], pages: list[Any]) -> dict[str, Any]:
    """Nieuwe, verdwenen en kapotgegane pagina's (op genormaliseerde URL)."""
    base = {page_key(p): p for p in base_pages}
    current = {page_key(p): p for p in pages}
    new = [p for key, p in current.items() if key not in base and is_crawled(p)]
    removed = [p for key, p in base.items() if key not in current and is_crawled(p)]
    broken = [
        (base[key], p) for key, p in current.items()
        if key in base and is_working(base[key]) and is_broken(p)
    ]
    return {
        "before": len([p for p in base_pages if is_crawled(p)]),
        "after": len([p for p in pages if is_crawled(p)]),
        "new": new,
        "removed": removed,
        "broken": broken,
    }


def lost_schema_types(base_pages: list[Any], pages: list[Any]) -> list[dict[str, Any]]:
    """Pagina's die in beide scans werken maar schema-types kwijt zijn."""
    base = {page_key(p): p for p in base_pages}
    out: list[dict[str, Any]] = []
    for page in pages:
        before = base.get(page_key(page))
        if before is None or not (is_working(before) and is_working(page)):
            continue
        lost = sorted(set(before.schema_types or []) - set(page.schema_types or []))
        if lost:
            out.append({"url": page.url, "lost": lost})
    return out


# --- AI-vindbaarheid -------------------------------------------------------------

def compare_ai(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    old = {c.get("key"): c for c in before.get("checks") or []}
    rows: list[dict[str, Any]] = []
    for check in after.get("checks") or []:
        key = check.get("key")
        prev = old.get(key) or {}
        prev_status, status = prev.get("status"), check.get("status")
        if prev_status is None:
            change = "new"
        elif _AI_RANK.get(status, 0) < _AI_RANK.get(prev_status, 0):
            change = "better"
        elif _AI_RANK.get(status, 0) > _AI_RANK.get(prev_status, 0):
            change = "worse"
        else:
            change = "same"
        rows.append({
            "key": key,
            "label": check.get("label") or key,
            "before": prev_status,
            "after": status,
            "message": check.get("message"),
            "change": change,
        })
    return {
        "before": before.get("score"),
        "after": after.get("score"),
        "checks": rows,
        "improved": len([r for r in rows if r["change"] == "better"]),
        "worsened": len([r for r in rows if r["change"] == "worse"]),
    }


# --- actiepunten ----------------------------------------------------------------

# Niet vergelijkbaar: fase 4-checklistpunten zelf, en Core Web Vitals (fase 4 meet die niet,
# dus de CWV-punten van de nulmeting zouden anders als 'opgelost' tellen).
_NOT_COMPARED_PREFIXES = (KEY_PREFIX, "cwv_")


def count_issue_types(issue_types: Iterable[str]) -> Counter[str]:
    """Telling per type, zonder types die fase 4 niet meet of vergelijkt."""
    return Counter(t for t in issue_types if not t.startswith(_NOT_COMPARED_PREFIXES))


def scan_ruleset(scan: Any) -> int:
    """Regelset waarmee de actiepunten van een scan zijn gemaakt; scans zonder stempel = 1."""
    stats = getattr(scan, "summary_stats", None)
    value = stats.get("ruleset") if isinstance(stats, dict) else None
    return value if isinstance(value, int) and value > 0 else 1


def compare_issues(
    before: Counter[str], after: Counter[str], *, base_ruleset: int | None = None
) -> dict[str, Any]:
    """Aantallen per type voor en na.

    Met `base_ruleset` zijn types die pas in een latere regelset zijn toegevoegd
    niet vergelijkbaar: de basis-scan kon ze nog niet vinden. Die tellen niet mee
    in de totalen en komen als rij met `before: None`, `delta: None` en
    `comparable: False` (onderaan). `not_compared` is hun aantal in deze scan.
    """
    def comparable(t: str) -> bool:
        return base_ruleset is None or issue_type_since(t) <= base_ruleset

    def meta(t: str) -> dict[str, Any]:
        return {
            "issue_type": t,
            "label": ISSUE_TYPES.get(t, {}).get("label", t),
            "category": ISSUE_TYPES.get(t, {}).get("category", "techniek"),
        }

    types = set(before) | set(after)
    rows = [
        {
            **meta(t),
            "before": before.get(t, 0),
            "after": after.get(t, 0),
            "delta": after.get(t, 0) - before.get(t, 0),
            "comparable": True,
        }
        for t in types if comparable(t)
    ]
    rows.sort(key=lambda r: (-abs(r["delta"]), -r["after"], r["label"]))
    new_checks = [
        {**meta(t), "before": None, "after": after.get(t, 0), "delta": None, "comparable": False}
        for t in types if not comparable(t) and after.get(t, 0)
    ]
    new_checks.sort(key=lambda r: (-r["after"], r["label"]))
    return {
        "before": sum(n for t, n in before.items() if comparable(t)),
        "after": sum(n for t, n in after.items() if comparable(t)),
        "not_compared": sum(r["after"] for r in new_checks),
        "rows": rows + new_checks,
    }


# --- Ahrefs ----------------------------------------------------------------------

def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def compare_ahrefs(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    """Domeincijfers voor en na; None als geen van beide scans Ahrefs-data heeft."""
    old = (before or {}).get("domain") or {}
    new = (after or {}).get("domain") or {}
    if not old and not new:
        return None
    metrics = []
    for key, label in AHREFS_METRICS:
        b, a = _num(old.get(key)), _num(new.get(key))
        metrics.append({
            "key": key,
            "label": label,
            "before": b,
            "after": a,
            "delta": (a - b) if a is not None and b is not None else None,
        })
    fetched_before = (before or {}).get("fetched_at")
    fetched_after = (after or {}).get("fetched_at")
    return {
        "metrics": metrics,
        "fetched_before": fetched_before,
        "fetched_after": fetched_after,
        # Binnen de bewaartermijn hergebruikt de scan de Ahrefs-data: dan is er niets te vergelijken.
        "same_snapshot": bool(fetched_before) and fetched_before == fetched_after,
        "lost_value_urls": (after or {}).get("lost_value_urls"),
    }


# --- Search Console ---------------------------------------------------------------

GSC_METRICS: list[tuple[str, str]] = [
    ("clicks", "Klikken"),
    ("impressions", "Vertoningen"),
    ("ctr", "CTR"),
    ("position", "Gemiddelde positie"),
]
MAX_MOVERS = 15


def _movers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Top, stijgers en dalers op klikken. Rijen zonder vorige waarde tellen niet mee als beweging."""
    compared = [
        {**r, "delta": r["clicks"] - r["clicks_prev"]}
        for r in rows
        if r.get("clicks") is not None and r.get("clicks_prev") is not None
    ]
    return {
        "total": len(rows),
        "top": [r for r in rows if r.get("clicks")][:MAX_MOVERS],
        "risers": sorted((r for r in compared if r["delta"] > 0), key=lambda r: -r["delta"])[:MAX_MOVERS],
        "fallers": sorted((r for r in compared if r["delta"] < 0), key=lambda r: r["delta"])[:MAX_MOVERS],
    }


def compare_search_console(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Search Console-cijfers van de meetperiode naast de periode ervoor en vorig jaar.

    De vorige periode komt rechtstreeks uit Search Console, niet uit de basis-scan:
    ook de eerste ronde heeft dus een vergelijking. None zonder bruikbare data.
    """
    if not snapshot or (snapshot.get("totals") is None and snapshot.get("sitemaps") is None):
        return None
    cur = snapshot.get("totals") or {}
    prev = snapshot.get("totals_previous") or {}
    last_year = snapshot.get("totals_last_year") or {}
    metrics = []
    for key, label in GSC_METRICS:
        b, a, y = _num(prev.get(key)), _num(cur.get(key)), _num(last_year.get(key))
        metrics.append({
            "key": key,
            "label": label,
            "before": b,
            "after": a,
            "delta": (a - b) if a is not None and b is not None else None,
            "pct": round(100 * (a - b) / b, 1) if a is not None and b else None,
            "last_year": y,
            "pct_last_year": round(100 * (a - y) / y, 1) if a is not None and y else None,
        })
    sitemaps = snapshot.get("sitemaps")
    inspection = snapshot.get("inspection")
    return {
        "property": snapshot.get("property"),
        "property_source": snapshot.get("property_source"),
        "period": snapshot.get("period"),
        "previous": snapshot.get("previous"),
        "last_year": snapshot.get("last_year"),
        "has_performance": snapshot.get("totals") is not None,
        "metrics": metrics,
        "queries": _movers(snapshot.get("queries") or []),
        "pages": _movers(snapshot.get("pages") or []),
        "sitemaps": None if sitemaps is None else {
            "total": len(sitemaps),
            "with_errors": len([s for s in sitemaps if s.get("errors")]),
            "with_warnings": len([s for s in sitemaps if s.get("warnings")]),
            "rows": sitemaps[:MAX_LIST],
        },
        "inspection": _inspection_summary(inspection) if inspection else None,
        "fetched_at": snapshot.get("fetched_at"),
    }


def _inspection_summary(inspection: dict[str, Any]) -> dict[str, Any]:
    """URL-inspectie samengevat: dekking, niet-geïndexeerde URL's en rich-results-meldingen.

    `eligible` is het aantal pagina's dat in aanmerking kwam (None bij scans van
    vóór de volledige inspectie); `complete` zegt of ze allemaal zijn gecontroleerd.
    """
    rows = inspection.get("rows") or []
    checked = inspection.get("checked") or 0
    eligible = inspection.get("eligible")
    rich_rows = []
    for row in rows:
        rich = row.get("rich_results") or {}
        issues = rich.get("issues") or []
        if issues:
            rich_rows.append({
                "url": row.get("url"),
                "link": row.get("link"),
                "types": rich.get("types") or [],
                "errors": len([i for i in issues if i.get("severity") == "ERROR"]),
                "issues": sorted(issues, key=lambda i: i.get("severity") != "ERROR")[:MAX_RICH_ISSUES_PER_URL],
            })
    rich_rows.sort(key=lambda r: (not r["errors"], str(r["url"])))
    return {
        "requested": inspection.get("requested"),
        "eligible": eligible,
        "checked": checked,
        "indexed": inspection.get("indexed"),
        "complete": bool(eligible) and checked >= eligible,
        "stopped_reason": inspection.get("stopped_reason"),
        "not_indexed": [
            {k: r.get(k) for k in ("url", "state", "reason", "last_crawl_time", "google_canonical", "link")}
            for r in rows
            if r.get("state") != "indexed"
        ][:MAX_LIST],
        "with_rich_results": len([r for r in rows if r.get("rich_results")]),
        "rich_results": rich_rows[:MAX_LIST],
    }


# --- Bing Webmaster ------------------------------------------------------------------

BING_METRICS: list[tuple[str, str]] = [
    ("clicks", "Klikken"),
    ("impressions", "Vertoningen"),
    ("ctr", "CTR"),
]
# Stand van de crawl op de laatste dag, in de volgorde waarin ze getoond worden.
BING_CRAWL_FIELDS: list[tuple[str, str]] = [
    ("code_2xx", "Pagina's met 2xx"),
    ("code_301", "301-redirects"),
    ("code_302", "302-redirects"),
    ("code_4xx", "4xx-fouten"),
    ("code_5xx", "5xx-fouten"),
    ("blocked_by_robots", "Geblokkeerd door robots.txt"),
    ("dns_failures", "DNS-fouten"),
    ("connection_timeouts", "Time-outs"),
    ("contains_malware", "Malware"),
]
_FEED_OK = {"success", "ok"}
_FEED_PENDING = {"", "pending", "processing", "submitted", "inprogress", "in progress", "queued"}


def bing_feed_state(status: Any) -> str:
    """"ok", "pending" (nog niet verwerkt) of "error" voor de status van een sitemap in Bing."""
    value = str(status or "").strip().lower()
    if value in _FEED_OK:
        return "ok"
    return "pending" if value in _FEED_PENDING else "error"


def compare_bing_webmaster(
    snapshot: dict[str, Any] | None, base_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Bing Webmaster-cijfers van de meetperiode naast de periode ervoor.

    Klikken en vertoningen worden vergeleken met de even lange periode ervoor, uit
    Bing zelf. Het aantal pagina's in de index wordt vergeleken met de stand aan
    het begin van de meetperiode; kent Bing die niet meer, dan met de vorige ronde
    (`base_snapshot`). Zonder koppeling of zonder site in het account bevat het
    resultaat alleen `state` en `message`. None als de scan geen Bing-stap had.
    """
    if not snapshot:
        return None
    result: dict[str, Any] = {
        "state": snapshot.get("state"),
        "message": snapshot.get("message"),
        "site": snapshot.get("site"),
        "auth_mode": snapshot.get("auth_mode"),
        "has_data": False,
        "fetched_at": snapshot.get("fetched_at"),
    }
    if snapshot.get("state") != "ok":
        return result

    cur = snapshot.get("totals") or {}
    prev = snapshot.get("totals_previous") or {}
    metrics = []
    for key, label in BING_METRICS:
        b, a = _num(prev.get(key)), _num(cur.get(key))
        metrics.append({
            "key": key,
            "label": label,
            "before": b,
            "after": a,
            "delta": (a - b) if a is not None and b is not None else None,
            "pct": round(100 * (a - b) / b, 1) if a is not None and b else None,
        })

    crawl = snapshot.get("crawl")
    index = None
    if crawl:
        after = _num(crawl.get("in_index"))
        before, before_date, source = _num(crawl.get("in_index_before")), crawl.get("in_index_before_date"), "bing"
        base_crawl = (base_snapshot or {}).get("crawl") if (base_snapshot or {}).get("state") == "ok" else None
        if before is None and base_crawl:
            before, before_date, source = _num(base_crawl.get("in_index")), base_crawl.get("date"), "base"
        index = {
            "date": crawl.get("date"),
            "in_index": {
                "before": before,
                "after": after,
                "delta": (after - before) if after is not None and before is not None else None,
                "pct": round(100 * (after - before) / before, 1) if after is not None and before else None,
                "before_date": before_date,
                "before_source": source if before is not None else None,
            },
            "in_links": crawl.get("in_links"),
            "crawled_pages": crawl.get("crawled_pages"),
            "status": [{"key": key, "label": label, "value": crawl.get(key)} for key, label in BING_CRAWL_FIELDS],
        }

    feeds = snapshot.get("sitemaps")
    sitemaps = None
    if feeds is not None:
        rows = [{**feed, "state": bing_feed_state(feed.get("status"))} for feed in feeds]
        sitemaps = {
            "total": len(rows),
            "with_errors": len([r for r in rows if r["state"] == "error"]),
            "pending": len([r for r in rows if r["state"] == "pending"]),
            "rows": rows[:MAX_LIST],
        }

    crawl_issues = snapshot.get("crawl_issues")
    result.update({
        "has_data": bool(crawl) or bool(feeds) or snapshot.get("totals") is not None,
        "period": snapshot.get("period"),
        "previous": snapshot.get("previous"),
        "has_performance": snapshot.get("totals") is not None,
        "metrics": metrics,
        "queries": _movers(snapshot.get("queries") or []),
        "pages": _movers(snapshot.get("pages") or []),
        "index": index,
        "crawl_issues": None if crawl_issues is None else {
            "total": crawl_issues.get("total") or 0,
            "rows": (crawl_issues.get("rows") or [])[:MAX_LIST],
        },
        "sitemaps": sitemaps,
    })
    return result


# --- posities (SEO-tracker) ----------------------------------------------------------

def compare_rankings(db: Session, customer_id: str, since: datetime | None) -> dict[str, Any] | None:
    """Laatste positie per zoekwoord nu en rond de basisdatum. None zonder metingen."""
    rows = (
        db.query(
            SerpScanResult.keyword_id,
            SerpScanResult.keyword,
            SerpScanResult.position,
            SerpScanResult.result_url,
            SerpScanResult.created_at,
        )
        .filter(SerpScanResult.website_id == customer_id, SerpScanResult.error_message.is_(None))
        .order_by(SerpScanResult.created_at.asc())
        .all()
    )
    if not rows:
        return None
    latest: dict[str, Any] = {}
    before: dict[str, Any] = {}
    for row in rows:
        latest[row.keyword_id] = row
        if since is not None and row.created_at <= since:
            before[row.keyword_id] = row

    def delta(old: int | None, new: int | None) -> int | None:
        # Positief = gestegen. Niet gevonden telt als positie 101.
        if old is None and new is None:
            return None
        return (old or 101) - (new or 101)

    items = []
    for keyword_id, row in latest.items():
        prev = before.get(keyword_id)
        old_pos = prev.position if prev is not None else None
        items.append({
            "keyword": row.keyword,
            "before": old_pos,
            "after": row.position,
            "delta": delta(old_pos, row.position) if prev is not None else None,
            "url": row.result_url,
            "checked_at": row.created_at.isoformat() if row.created_at else None,
        })
    items.sort(key=lambda r: (r["after"] is None, r["after"] or 0, r["keyword"]))
    with_delta = [r for r in items if r["delta"] is not None]
    return {
        "keywords": len(items),
        "top3": len([r for r in items if r["after"] is not None and r["after"] <= 3]),
        "top10": len([r for r in items if r["after"] is not None and r["after"] <= 10]),
        "improved": len([r for r in with_delta if r["delta"] > 0]),
        "declined": len([r for r in with_delta if r["delta"] < 0]),
        "compared": len(with_delta),
        "last_checked_at": max((r["checked_at"] or "" for r in items), default=None) or None,
        "rows": items[:MAX_RANKINGS],
    }


# --- basis ---------------------------------------------------------------------

def base_info(base: LaunchScan) -> dict[str, Any]:
    if base.phase == 4:
        label = f"Ronde {period_label(base.period)}"
    else:
        label = "Nulmeting (fase 1)"
    return {
        "scan_id": base.id,
        "phase": base.phase,
        "period": base.period,
        "label": label,
        "completed_at": base.completed_at.isoformat() if base.completed_at else None,
    }
