"""Auto-resultaten van de fase-4 checklist.

Elk resultaat heeft dezelfde vorm als in fase 2 en 3:
`{status, message, evidence, details}`. `c4_proranktracker` is handmatig en
krijgt geen auto-resultaat; `c4_search_console` alleen als Search Console is
gekoppeld. `c4_bing_webmaster` krijgt altijd een resultaat: zonder koppeling of
zonder site in het Bing-account zegt het dat de controle handmatig moet.
"""
from __future__ import annotations

from typing import Any

from app.features.launch_checklist.services.discovery import url_key
from app.features.launch_checklist.services.issues import final_status
from app.features.launch_checklist.services.quarterly_compare import MAX_LIST, is_broken
from app.features.launch_checklist.services.schema_validate import describe_problem

MAX_EVIDENCE = 15


def _r(status: str, message: str, evidence: list[Any] | None = None, details: Any = None) -> dict[str, Any]:
    return {"status": status, "message": message, "evidence": (evidence or [])[:MAX_EVIDENCE], "details": details}


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


# --- c4_ai_scan ------------------------------------------------------------------

def evaluate_ai_scan(ai: dict[str, Any], base_label: str) -> dict[str, Any]:
    before, after = ai.get("before"), ai.get("after")
    worse = [r for r in ai.get("checks") or [] if r["change"] == "worse"]
    better = [r for r in ai.get("checks") or [] if r["change"] == "better"]
    if after is None:
        return _r("unknown", "Geen AI-checks in deze scan.")
    score = f"AI-score {before} → {after}" if before is not None else f"AI-score {after}"
    if before is not None:
        diff = after - before
        score += f" ({'+' if diff >= 0 else ''}{diff})"
    message = (
        f"{score} t.o.v. {base_label.lower()}; "
        f"{_plural(len(better), 'punt', 'punten')} verbeterd, {len(worse)} verslechterd."
    )
    evidence = [f"{r['label']}: {r['before'] or '—'} → {r['after']}" for r in worse + better]
    if any(r["after"] == "error" for r in worse):
        status = "error"
    elif worse or (before is not None and after < before):
        status = "warning"
    else:
        status = "ok"
    return _r(status, message, evidence, {"before": before, "after": after, "checks": ai.get("checks") or []})


# --- c4_new_pages ----------------------------------------------------------------

def _new_page_problems(page: Any, discovery_source: str | None) -> tuple[str, list[str]]:
    """(status, problemen) van één nieuwe pagina."""
    status_code = final_status(page)
    if is_broken(page):
        label = f"geeft {status_code}" if status_code else f"niet bereikbaar ({page.error or 'fout'})"
        return "error", [label]
    problems: list[str] = []
    hops = [h for h in (page.redirect_chain or []) if isinstance(h, dict) and not h.get("final")]
    if hops:
        problems.append("stuurt door naar " + str(page.final_url or "een andere URL"))
    if page.indexable is False:
        problems.append(f"niet indexeerbaar ({page.indexability_reason or 'noindex'})")
    canonical = (page.canonical or "").strip()
    if canonical and page.indexable is not False and url_key(canonical) != url_key(page.final_url or page.url):
        problems.append(f"canonical wijst naar {canonical}")
    if discovery_source == "sitemap" and not page.in_sitemap and not hops and page.indexable is not False:
        problems.append("staat niet in de sitemap")
    return ("warning" if problems else "ok"), problems


def evaluate_new_pages(
    pages_diff: dict[str, Any],
    discovery_source: str | None,
    base_label: str,
    inspection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`inspection`: URL-inspectie uit Search Console (`snapshot["inspection"]`), als die er is.

    De indexstatus van Google staat per nieuwe pagina in de details; het oordeel
    daarover valt onder `c4_search_console`.
    """
    google = {url_key(r["url"]): r for r in (inspection or {}).get("rows") or [] if r.get("url")}
    new_rows: list[dict[str, Any]] = []
    for page in pages_diff["new"]:
        status, problems = _new_page_problems(page, discovery_source)
        inspected = google.get(url_key(page.final_url or page.url)) or google.get(url_key(page.url))
        new_rows.append({
            "google": {"state": inspected.get("state"), "reason": inspected.get("reason")} if inspected else None,
            "page_id": page.id,
            "url": page.url,
            "path": page.path,
            "status_code": final_status(page),
            "indexable": page.indexable,
            "in_sitemap": page.in_sitemap,
            "result": status,
            "problems": problems,
        })
    new_rows.sort(key=lambda r: ({"error": 0, "warning": 1, "ok": 2}[r["result"]], r["path"]))
    broken_rows = [
        {
            "page_id": page.id,
            "url": page.url,
            "path": page.path,
            "before": final_status(before),
            "status_code": final_status(page),
        }
        for before, page in pages_diff["broken"]
    ]
    removed = [p.url for p in pages_diff["removed"]]

    errors = [r for r in new_rows if r["result"] == "error"]
    warnings = [r for r in new_rows if r["result"] == "warning"]
    details = {
        "new_total": len(new_rows),
        "new": new_rows[:MAX_LIST],
        "broken_total": len(broken_rows),
        "broken": broken_rows[:MAX_LIST],
        "removed_total": len(removed),
        "removed": removed[:MAX_LIST],
    }
    evidence = (
        [f"{r['status_code'] or 'fout'} (was {r['before']}) · {r['url']}" for r in broken_rows]
        + [f"{', '.join(r['problems'])} · {r['url']}" for r in errors + warnings]
    )
    since = f"sinds {base_label.lower()}"
    parts = [_plural(len(new_rows), "nieuwe pagina", "nieuwe pagina's") + f" {since}"]
    if errors or warnings:
        parts.append(f"{len(errors)} met een fout, {len(warnings)} met een aandachtspunt")
    if broken_rows:
        parts.append(_plural(len(broken_rows), "pagina werkte eerder en geeft nu een fout",
                             "pagina's werkten eerder en geven nu een fout"))
    message = "; ".join(parts) + "."
    if not new_rows and not broken_rows:
        message = f"Geen nieuwe pagina's en geen nieuwe 404's {since}."
    elif not errors and not warnings and not broken_rows:
        message += " Alle nieuwe pagina's zijn bereikbaar en indexeerbaar."
    if errors or broken_rows:
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "ok"
    return _r(status, message, evidence, details)


# --- c4_schema_validation ----------------------------------------------------------

def evaluate_schema(pages: list[Any], lost_types: list[dict[str, Any]]) -> dict[str, Any]:
    """`pages`: fase 4-pagina's met `signals["schema_validation"]` (opnieuw opgehaald)."""
    checked = [p for p in pages if isinstance((p.signals or {}).get("schema_validation"), dict)]
    if not checked:
        return _r("unknown", "Geen pagina's opgehaald voor de schema-validatie.")
    lost_by_url = {row["url"]: row["lost"] for row in lost_types}
    rows: list[dict[str, Any]] = []
    with_schema = 0
    for page in checked:
        result = page.signals["schema_validation"]
        if result.get("blocks"):
            with_schema += 1
        problems = result.get("problems") or []
        invalid = int(result.get("invalid_blocks") or 0)
        lost = lost_by_url.get(page.url) or []
        errors = [p for p in problems if p.get("severity") == "error"]
        if not (problems or invalid or lost):
            continue
        rows.append({
            "page_id": page.id,
            "url": page.url,
            "path": page.path,
            "result": "error" if errors or invalid else "warning",
            "invalid_blocks": invalid,
            "problems": problems,
            "lost_types": lost,
        })
    rows.sort(key=lambda r: (r["result"] != "error", r["path"]))
    error_pages = [r for r in rows if r["result"] == "error"]
    warning_pages = [r for r in rows if r["result"] == "warning"]

    def summary(row: dict[str, Any]) -> str:
        parts = [describe_problem(p) for p in row["problems"][:2]]
        if row["invalid_blocks"]:
            parts.insert(0, f"{row['invalid_blocks']}× ongeldige JSON")
        if row["lost_types"]:
            parts.append("verdwenen: " + ", ".join(row["lost_types"]))
        return "; ".join(parts)

    evidence = [f"{summary(r)} · {r['url']}" for r in rows]
    checked_label = _plural(len(checked), "pagina", "pagina's")
    base = f"{checked_label} gecontroleerd, {with_schema} met JSON-LD"
    if error_pages:
        status = "error"
        error_label = _plural(len(error_pages), "pagina heeft", "pagina's hebben")
        message = f"{base}: {error_label} schemafouten"
        if warning_pages:
            message += f", {len(warning_pages)} een aandachtspunt"
        message += "."
    elif warning_pages:
        status = "warning"
        warning_label = _plural(len(warning_pages), "pagina", "pagina's")
        message = f"{base}: geen fouten, wel {warning_label} met een aandachtspunt."
    else:
        status = "ok"
        message = f"{base}: geen fouten gevonden."
    details = {
        "checked": len(checked),
        "with_schema": with_schema,
        "error_pages": len(error_pages),
        "warning_pages": len(warning_pages),
        "pages": rows[:MAX_LIST],
    }
    return _r(status, message, evidence, details)


# --- c4_search_console -----------------------------------------------------------------

PAGES = "pagina's"


def _nl(value: Any) -> str:
    return f"{int(value):,}".replace(",", ".")


def evaluate_search_console(gsc: dict[str, Any] | None, clicks_drop_warn_pct: int = 20) -> dict[str, Any]:
    """`gsc`: resultaat van `compare_search_console`.

    De rapporten Pagina-indexering en Verbeteringen zitten niet in de API; de
    scan benadert ze met de URL-inspectie per pagina (indexstatus en rich
    results). Alleen als alle indexeerbare pagina's zijn geïnspecteerd en ook de
    klikken en sitemaps zijn opgehaald, kan de status "ok" worden. Anders blijft
    het punt zonder problemen open ("info") tot het handmatig is afgevinkt.
    Bing Webmaster heeft een eigen punt (`c4_bing_webmaster`).
    """
    if not gsc:
        return _r("unknown", "Geen Search Console-data in deze scan (zie de waarschuwingen bij de scan).")
    parts: list[str] = []
    evidence: list[str] = []
    errors = warnings = 0

    clicks = next((m for m in gsc.get("metrics") or [] if m["key"] == "clicks"), None)
    drop_pct = None
    if clicks and clicks.get("after") is not None:
        text = f"{_nl(clicks['after'])} klikken"
        if clicks.get("before") is not None:
            text = f"klikken {_nl(clicks['before'])} → {_nl(clicks['after'])}"
            if clicks.get("pct") is not None:
                text += f" ({'+' if clicks['pct'] >= 0 else ''}{clicks['pct']:g}%)"
                if clicks["pct"] <= -clicks_drop_warn_pct:
                    drop_pct = clicks["pct"]
                    warnings += 1
                    evidence.append(f"Klikken {abs(drop_pct):g}% gedaald t.o.v. de vorige periode")
        days = (gsc.get("period") or {}).get("days")
        parts.append(text + (f" in {days} dagen" if days else ""))

    sitemaps = gsc.get("sitemaps")
    bad_sitemaps: list[dict[str, Any]] = []
    if sitemaps is not None:
        bad_sitemaps = [s for s in sitemaps.get("rows") or [] if s.get("errors") or s.get("warnings")]
        with_errors = [s for s in bad_sitemaps if s.get("errors")]
        errors += len(with_errors)
        warnings += len(bad_sitemaps) - len(with_errors)
        if not sitemaps.get("total"):
            warnings += 1
            parts.append("geen sitemap ingediend")
            evidence.append("Er is geen sitemap ingediend in Search Console")
        else:
            parts.append(f"{_plural(sitemaps['total'], 'sitemap', 'sitemaps')}, {len(with_errors)} met fouten")
        evidence += [
            f"Sitemap: {_plural(s.get('errors') or 0, 'fout', 'fouten')}, "
            f"{_plural(s.get('warnings') or 0, 'waarschuwing', 'waarschuwingen')} · {s.get('path')}"
            for s in bad_sitemaps
        ]

    inspection = gsc.get("inspection")
    not_indexed: list[dict[str, Any]] = []
    rich_errors: list[dict[str, Any]] = []
    coverage: dict[str, Any] | None = None
    if inspection:
        not_indexed = inspection.get("not_indexed") or []
        blocked = [r for r in not_indexed if r.get("state") == "blocked"]
        errors += len(blocked)
        warnings += len(not_indexed) - len(blocked)
        # Alleen fouten tellen mee; waarschuwingen van Google gaan over optionele velden.
        rich_errors = [r for r in inspection.get("rich_results") or [] if r.get("errors")]
        errors += len(rich_errors)
        checked, eligible = inspection.get("checked") or 0, inspection.get("eligible")
        coverage = {
            "eligible": eligible,
            "checked": checked,
            "indexed": inspection.get("indexed") or 0,
            "complete": bool(inspection.get("complete")),
        }
        if eligible:
            inspected = f"{checked} van {_plural(eligible, 'pagina', PAGES)}"
        else:  # scan van vóór de volledige inspectie: alleen de homepage en nieuwe pagina's
            inspected = _plural(checked, "URL", "URL's")
        parts.append(f"{inspected} geïnspecteerd, {coverage['indexed']} geïndexeerd")
        if rich_errors:
            parts.append(f"{_plural(len(rich_errors), 'pagina', PAGES)} met rich-results-fouten")
        elif inspection.get("with_rich_results"):
            parts.append("geen rich-results-fouten")
        evidence += [f"Niet geïndexeerd ({r.get('reason')}) · {r.get('url')}" for r in blocked + [
            r for r in not_indexed if r.get("state") != "blocked"
        ]]
        evidence += [
            f"Rich results: {_plural(r['errors'], 'fout', 'fouten')} "
            f"({', '.join(r.get('types') or []) or 'onbekend type'}) · {r.get('url')}"
            for r in rich_errors
        ]

    # Zonder volledige dekking of zonder klikken of sitemaps valt "niets mis" niet te zeggen.
    missing: list[str] = []
    if not gsc.get("has_performance"):
        missing.append("de klikken zijn niet opgehaald")
    if sitemaps is None:
        missing.append("de sitemaps zijn niet opgehaald")
    if not coverage:
        missing.append("er zijn geen pagina's geïnspecteerd")
    elif not coverage["complete"]:
        missing.append("niet alle indexeerbare pagina's zijn geïnspecteerd")

    summary = "; ".join(parts)
    message = f"{summary[:1].upper()}{summary[1:]}." if summary else ""
    if errors:
        status = "error"
    elif warnings:
        status = "warning"
    elif missing:
        status = "info"
    else:
        status = "ok"
    if missing:
        message += (
            f" Let op: {' en '.join(missing)}. Controleer het rapport Pagina-indexering zelf en vink dit "
            "punt daarna af."
        )
    details = {
        "property": gsc.get("property"),
        "clicks_drop_pct": drop_pct,
        "sitemaps": bad_sitemaps[:MAX_LIST],
        "inspection": coverage,
        "not_indexed": not_indexed[:MAX_LIST],
        "rich_results": (inspection or {}).get("rich_results") or [],
    }
    return _r(status, message.strip(), evidence, details)


# --- c4_bing_webmaster -----------------------------------------------------------------

# Onder deze aantallen zegt een procentuele daling niets.
BING_MIN_CLICKS_FOR_DROP = 20
BING_MIN_INDEX_FOR_DROP = 10
BING_INDEX_DROP_WARN_PCT = 20
_BING_MANUAL = "Voer deze controle handmatig uit in Bing Webmaster Tools en vink het punt daarna af."


def evaluate_bing_webmaster(bing: dict[str, Any] | None, clicks_drop_warn_pct: int = 20) -> dict[str, Any]:
    """`bing`: resultaat van `compare_bing_webmaster`.

    Dit punt krijgt altijd een resultaat. Zonder koppeling, of als de site niet in
    het Bing-account staat, is dat "info": het punt blijft open en wordt handmatig
    gedaan. Met data en zonder problemen is het "ok" en telt het als afgerond.
    """
    if not bing:
        return _r("info", "Bing Webmaster is niet gekoppeld. " + _BING_MANUAL, details={"state": "not_connected"})
    state = bing.get("state")
    site = bing.get("site")
    if state != "ok":
        message = bing.get("message") or "Bing Webmaster-data is niet opgehaald. " + _BING_MANUAL
        return _r("info", message, details={"state": state, "site": site})
    if not bing.get("has_data"):
        return _r(
            "info",
            "De site staat in Bing Webmaster Tools, maar Bing heeft nog geen data. Scan later opnieuw of voer "
            "deze controle handmatig uit.",
            details={"state": "no_data", "site": site},
        )

    parts: list[str] = []
    evidence: list[str] = []
    errors = warnings = 0

    index = bing.get("index") or {}
    in_index = index.get("in_index") or {}
    index_drop_pct = None
    status_counts = {row["key"]: row.get("value") or 0 for row in index.get("status") or []}
    if in_index.get("after") is not None:
        text = f"{_nl(in_index['after'])} pagina's in de Bing-index"
        if in_index.get("before") is not None:
            text += f" (was {_nl(in_index['before'])})"
            pct = in_index.get("pct")
            if pct is not None and in_index["before"] >= BING_MIN_INDEX_FOR_DROP and pct <= -BING_INDEX_DROP_WARN_PCT:
                index_drop_pct = pct
                warnings += 1
                evidence.append(f"Aantal pagina's in de Bing-index {abs(pct):g}% gedaald")
        parts.append(text)
        if in_index["after"] == 0:
            warnings += 1
            evidence.append("Bing heeft geen enkele pagina van de site in de index")
    malware = int(status_counts.get("contains_malware") or 0)
    if malware:
        errors += 1
        evidence.append("Bing meldt malware op " + _plural(malware, "URL", "URL's"))
    server_errors = int(status_counts.get("code_5xx") or 0)
    if server_errors:
        warnings += 1
        evidence.append(_plural(server_errors, "URL geeft", "URL's geven") + " een serverfout (5xx) aan Bingbot")
    for key, label in (("dns_failures", "DNS-fouten"), ("connection_timeouts", "time-outs")):
        if int(status_counts.get(key) or 0):
            warnings += 1
            evidence.append(f"Bingbot meldt {status_counts[key]} {label}")

    crawl_issues = bing.get("crawl_issues")
    issue_rows: list[dict[str, Any]] = []
    if crawl_issues is not None:
        issue_rows = crawl_issues.get("rows") or []
        severe = [r for r in issue_rows if r.get("severe")]
        errors += len(severe)
        warnings += len(issue_rows) - len(severe)
        total = crawl_issues.get("total") or 0
        parts.append(_plural(total, "URL met een crawlfout", "URL's met een crawlfout") if total else "geen crawlfouten")
        evidence += [
            f"{', '.join(i['label'] for i in r.get('issues') or []) or 'crawlfout'} · {r.get('url')}"
            for r in severe + [r for r in issue_rows if not r.get("severe")]
        ]

    sitemaps = bing.get("sitemaps")
    bad_sitemaps: list[dict[str, Any]] = []
    no_sitemap = False
    if sitemaps is not None:
        bad_sitemaps = [s for s in sitemaps.get("rows") or [] if s.get("state") == "error"]
        errors += len(bad_sitemaps)
        if not sitemaps.get("total"):
            no_sitemap = True
            warnings += 1
            parts.append("geen sitemap ingediend")
            evidence.append("Er is geen sitemap ingediend in Bing Webmaster Tools")
        else:
            parts.append(f"{_plural(sitemaps['total'], 'sitemap', 'sitemaps')}, {len(bad_sitemaps)} met fouten")
        evidence += [f"Sitemap met status {s.get('status') or 'onbekend'} · {s.get('url')}" for s in bad_sitemaps]

    clicks = next((m for m in bing.get("metrics") or [] if m["key"] == "clicks"), None)
    clicks_drop_pct = None
    if clicks and clicks.get("after") is not None:
        text = f"{_nl(clicks['after'])} klikken"
        if clicks.get("before") is not None:
            text = f"klikken {_nl(clicks['before'])} → {_nl(clicks['after'])}"
            pct = clicks.get("pct")
            if pct is not None:
                text += f" ({'+' if pct >= 0 else ''}{pct:g}%)"
                if clicks["before"] >= BING_MIN_CLICKS_FOR_DROP and pct <= -clicks_drop_warn_pct:
                    clicks_drop_pct = pct
                    warnings += 1
                    evidence.append(f"Klikken uit Bing {abs(pct):g}% gedaald t.o.v. de vorige periode")
        days = (bing.get("period") or {}).get("days")
        parts.append(text + (f" in {days} dagen" if days else ""))

    status = "error" if errors else "warning" if warnings else "ok"
    summary = "; ".join(parts)
    message = f"{summary[:1].upper()}{summary[1:]}." if summary else "Bing Webmaster-data opgehaald."
    if status == "ok":
        message += " Geen problemen gevonden in Bing Webmaster."
    details = {
        "state": "ok",
        "site": site,
        "index_drop_pct": index_drop_pct,
        "clicks_drop_pct": clicks_drop_pct,
        "malware": malware,
        "server_errors": server_errors,
        "no_sitemap": no_sitemap,
        "sitemaps": bad_sitemaps[:MAX_LIST],
        "crawl_issues_total": (crawl_issues or {}).get("total") or 0,
        "crawl_issues": issue_rows[:MAX_LIST],
    }
    return _r(status, message, evidence, details)


# --- c4_monthly_report -----------------------------------------------------------------

def evaluate_report(has_report: bool, has_search_console: bool = False) -> dict[str, Any]:
    if has_report:
        fill_in = "Vul GA4 aan" if has_search_console else "Vul Search Console en GA4 aan"
        return _r("info", f"Conceptrapport staat klaar (tabblad Rapportage). {fill_in} en "
                          "vink dit punt af als de rapportage is verstuurd.")
    return _r("unknown", "Er is geen conceptrapport gegenereerd (zie de waarschuwingen bij de scan).")
