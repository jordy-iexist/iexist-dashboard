"""Livegang (fase 5): de automatische resultaten van de livegangchecklist.

Eén resultaat per auto- en hybride punt (zelfde vorm als de andere fases:
status, message, evidence, details). Handmatige punten krijgen niets.

- Hybride punten geven nooit 'ok': `effective_status` zou ze dan afvinken zonder
  dat iemand gekeken heeft. Ze geven 'info', 'warning' of 'unknown'.
- Als de scanner op de meeste pagina's geblokkeerd werd, worden de punten die op
  pagina-inhoud leunen 'unknown', in plaats van een vals 'in orde'.
- Lijsten in `details` zijn gecapt op MAX_LIST, met het echte totaal ernaast.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

from app.features.launch_checklist.services.discovery import DiscoveryResult, parse_robots_sitemaps
from app.features.launch_checklist.services.golive_checklist import ITEMS
from app.features.launch_checklist.services.golive_extract import GoLiveSite, classify_host
from app.features.launch_checklist.services.golive_probes import BLOCKED_STATUSES, origin_of
from app.features.launch_checklist.services.inventory import PageRecord
from app.features.launch_checklist.services.robots_rules import parse_robots

MAX_LIST = 25
MAX_EVIDENCE = 10
GOOGLEBOT = "Googlebot"
_RANK = {"ok": 0, "nvt": 0, "info": 0, "unknown": 1, "warning": 2, "error": 3}
_TRACKING_NOTE = (
    "Tags die server-side of via een tagmanager worden geladen, zijn voor deze scan onzichtbaar."
)


def _r(status: str, message: str, evidence: list[Any] | None = None, details: Any = None) -> dict[str, Any]:
    return {"status": status, "message": message, "evidence": (evidence or [])[:MAX_EVIDENCE], "details": details}


def _worst(statuses: Iterable[str]) -> str:
    return max(statuses, key=lambda s: _RANK.get(s, 0), default="ok")


def _capped(items: list[Any]) -> list[Any]:
    return items[:MAX_LIST]


def _more(total: int, shown: int) -> str:
    return f" (en nog {total - shown})" if total > shown else ""


def _blocked_message(blocked: int, total: int) -> str:
    return (
        f"Niet te beoordelen: {blocked} van de {total} pagina's gaven 401/403/429/503, de scanner "
        "werd waarschijnlijk geblokkeerd door een firewall of bot-protectie."
    )


def _signals(rec: PageRecord) -> dict[str, Any] | None:
    data = rec.extra.get("golive") if rec.extra else None
    return data if isinstance(data, dict) and "error" not in data else None


def _is_home(rec: PageRecord) -> bool:
    for candidate in (rec.final_url, rec.url):
        if candidate:
            parsed = urlparse(candidate)
            if parsed.path in ("", "/") and not parsed.query:
                return True
    return False


def _page(rec: PageRecord) -> str:
    return rec.final_url or rec.url


def _chain_text(variant: dict[str, Any]) -> str:
    steps = [f"{hop['url']} ({hop['status']})" for hop in variant.get("chain") or []]
    if variant.get("error"):
        steps.append(variant["error"])
    elif variant.get("final_url"):
        steps.append(f"{variant['final_url']} ({variant['final_status']})")
    return " → ".join(steps) or variant.get("start", "")


def _hops(variant: dict[str, Any]) -> int:
    return len(variant.get("chain") or [])


def _temporary_hops(variant: dict[str, Any]) -> list[int]:
    return [hop["status"] for hop in variant.get("chain") or [] if hop.get("status") in (302, 303, 307)]


# --- domein, HTTPS & redirects ---------------------------------------------------

def check_https(probes: dict[str, Any]) -> dict[str, Any]:
    variant = probes.get("https")
    if not variant:
        return _r("unknown", "De https-homepage is niet gecontroleerd.")
    hsts = variant.get("hsts")
    hsts_text = f" HSTS staat aan ({hsts})." if hsts else " Geen HSTS-header (alleen ter informatie)."
    details = {"variant": variant, "hsts": hsts}
    evidence = [_chain_text(variant)]
    if variant.get("error"):
        return _r("error", f"HTTPS werkt niet: {variant['error']}", evidence, details)
    final_url = variant.get("final_url") or ""
    status = variant.get("final_status")
    if not final_url.startswith("https://"):
        return _r("error", f"De https-homepage verwijst terug naar http:// ({final_url}).", evidence, details)
    if status in BLOCKED_STATUSES:
        return _r("unknown", f"Het certificaat is geldig, maar de homepage gaf {status}: de scanner wordt "
                  "waarschijnlijk geblokkeerd.", evidence, details)
    if status != 200:
        return _r("error", f"De https-homepage geeft statuscode {status}.", evidence, details)
    return _r("ok", f"Bereikbaar via HTTPS met een geldig certificaat ({final_url}).{hsts_text}", evidence, details)


def check_http_redirect(probes: dict[str, Any]) -> dict[str, Any]:
    variants = [v for v in probes.get("variants") or [] if v.get("scheme") == "http"]
    if not variants:
        return _r("unknown", "De http://-varianten zijn niet gecontroleerd.")
    rows = []
    for v in variants:
        temporary = _temporary_hops(v)
        final = v.get("final_url") or ""
        if v.get("error"):
            status, note = "warning", f"niet bereikbaar ({v['error']})"
        elif not v.get("chain"):
            if v.get("final_status") in BLOCKED_STATUSES:
                status, note = "unknown", f"statuscode {v['final_status']} (scanner geblokkeerd?)"
            elif v.get("final_status") == 200:
                status, note = "error", "geeft zelf een pagina (200) via http, zonder redirect"
            else:
                status, note = "warning", f"statuscode {v.get('final_status')} zonder redirect naar https"
        elif not final.startswith("https://"):
            status, note = "error", f"komt niet uit op https ({final})"
        elif temporary:
            status, note = "warning", f"tijdelijke redirect ({', '.join(map(str, temporary))}) in plaats van 301"
        else:
            status, note = "ok", f"{v['chain'][0]['status']} naar {final}"
        rows.append({"start": v["start"], "status": status, "note": note, "chain": v.get("chain") or [],
                     "final_url": v.get("final_url"), "final_status": v.get("final_status"), "error": v.get("error")})
    worst = _worst(r["status"] for r in rows)
    evidence = [f"{r['start']}: {r['note']}" for r in rows]
    messages = {
        "ok": "http:// verwijst met een permanente redirect (301/308) door naar https://.",
        "warning": "http:// gaat niet overal met een permanente redirect naar https://.",
        "error": "http:// verwijst niet (overal) door naar https://.",
        "unknown": "De http://-varianten konden niet worden beoordeeld.",
    }
    return _r(worst, messages[worst], evidence, {"variants": rows})


def check_host_variants(probes: dict[str, Any], site: GoLiveSite) -> dict[str, Any]:
    if not site.has_host_pair:
        return _r("nvt", f"De site staat op een subdomein ({site.host}): er is geen www/apex-paar.")
    variants = probes.get("variants") or []
    base = probes.get("https") or {}
    target = origin_of(base.get("final_url")) if base.get("final_status") == 200 else None
    rows = []
    for v in variants:
        end = origin_of(v.get("final_url"))
        if v.get("error"):
            status, note = "warning", f"niet bereikbaar ({v['error']})"
        elif v.get("final_status") in BLOCKED_STATUSES:
            status, note = "unknown", f"statuscode {v['final_status']} (scanner geblokkeerd?)"
        elif v.get("final_status") != 200:
            status, note = "warning", f"eindigt op statuscode {v.get('final_status')}"
        elif target is None:
            status, note = "unknown", "de https-homepage geeft geen 200"
        elif end != target:
            status, note = "error", (
                f"geeft een eigen pagina op {end}" if not v.get("chain") else f"komt uit op {end} in plaats van {target}"
            )
        elif _hops(v) > 2:
            status, note = "warning", f"{_hops(v)} redirects (meer dan twee)"
        elif _temporary_hops(v):
            status, note = "warning", "tijdelijke redirect in de keten"
        else:
            status, note = "ok", f"komt uit op {target}" + (f" ({_hops(v)} redirect(s))" if v.get("chain") else "")
        rows.append({
            "start": v["start"], "status": status, "note": note, "chain": v.get("chain") or [],
            "final_url": v.get("final_url"), "final_status": v.get("final_status"), "error": v.get("error"),
        })
    worst = _worst(r["status"] for r in rows)
    messages = {
        "ok": f"Alle varianten komen uit op {target}.",
        "warning": "Niet alle varianten komen netjes uit op één adres.",
        "error": "Niet alle varianten komen uit op hetzelfde adres: de site is op meer dan één adres bereikbaar.",
        "unknown": "De hostvarianten konden niet volledig worden beoordeeld.",
    }
    return _r(worst, messages[worst], [f"{r['start']}: {r['note']}" for r in rows],
              {"target": target, "variants": rows})


def check_mixed_content(parsed: list[PageRecord]) -> dict[str, Any]:
    https_pages = [r for r in parsed if _signals(r).get("https")]
    if not https_pages:
        return _r("unknown", "Geen https-pagina's om te controleren.")
    active, passive = [], []
    active_total = passive_total = 0
    active_pages = passive_pages = 0
    for rec in https_pages:
        sig = _signals(rec)
        active_total += sig.get("mixed_active_total", 0)
        passive_total += sig.get("mixed_passive_total", 0)
        active_pages += bool(sig.get("mixed_active_total"))
        passive_pages += bool(sig.get("mixed_passive_total"))
        active.extend({"page": _page(rec), **item} for item in sig.get("mixed_active") or [])
        passive.extend({"page": _page(rec), **item} for item in sig.get("mixed_passive") or [])
    details = {
        "pages_checked": len(https_pages),
        "active": _capped(active), "active_total": active_total, "active_pages": active_pages,
        "passive": _capped(passive), "passive_total": passive_total, "passive_pages": passive_pages,
    }
    evidence = [f"{i['page']}: <{i['tag']}> {i['url']}" for i in (active or passive)]
    if active_total:
        return _r("error", f"Actieve mixed content op {active_pages} pagina('s): {active_total} script(s), "
                  "stylesheet(s), iframe(s) of formulier(en) via http://. Browsers blokkeren die.", evidence, details)
    if passive_total:
        return _r("warning", f"Passieve mixed content op {passive_pages} pagina('s): {passive_total} afbeelding(en) "
                  "of media via http://.", evidence, details)
    return _r("ok", f"Geen mixed content op {len(https_pages)} https-pagina's.", details=details)


def check_internal_urls(parsed: list[PageRecord], site: GoLiveSite) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = 0
    by_issue: Counter[str] = Counter()
    for rec in parsed:
        sig = _signals(rec)
        total += sig.get("insecure_urls_total", 0)
        for item in sig.get("insecure_urls") or []:
            rows.append({"page": _page(rec), **item})
            for part in item["issue"].split("+"):
                by_issue[part] += 1
    canonicals = [r for r in rows if r["kind"] == "canonical"]
    details = {"urls": _capped(rows), "total": total, "http": by_issue["http"], "host": by_issue["host"],
               "canonicals": len(canonicals), "pages_checked": len(parsed)}
    if not total:
        return _r("ok", f"Interne links, canonicals en hreflang op {len(parsed)} pagina's gebruiken https en "
                  "het juiste adres.", details=details)
    parts = []
    if by_issue["http"]:
        parts.append(f"{by_issue['http']} via http://")
    if by_issue["host"]:
        parts.append(f"{by_issue['host']} naar de andere hostvariant ({' / '.join(sorted(site.hosts))})")
    evidence = [f"{r['page']}: {r['kind']} {r['url']}" for r in (canonicals or rows)]
    return _r("warning", f"{total} interne URL('s) wijzen naar een verkeerd adres: {', '.join(parts)}.",
              evidence, details)


# --- indexatie & testomgeving -----------------------------------------------------

def check_robots(records: list[PageRecord], discovery: DiscoveryResult, site: GoLiveSite,
                 home_url: str) -> dict[str, Any]:
    status = discovery.robots_status
    if status is None or status >= 500 or status == 429:
        return _r("unknown", "robots.txt kon niet worden opgehaald" + (f" (statuscode {status})." if status else "."))
    if status != 200:
        return _r("ok", f"Geen robots.txt (statuscode {status}): Google crawlt dan alles. Zet er een neer met "
                  "een verwijzing naar de sitemap.", details={"status": status})
    rules = parse_robots(discovery.robots_txt)
    urls = [home_url] + [r.url for r in records if (urlparse(r.url).hostname or "") in site.hosts | {site.host}]
    blocked: list[dict[str, Any]] = []
    seen: set[str] = set()
    home_rule: str | None = None
    for index, url in enumerate(urls):
        if url in seen:
            continue
        seen.add(url)
        allowed, rule = rules.check(GOOGLEBOT, url)
        if index == 0:
            if not allowed:
                home_rule = rule
            continue
        if not allowed:
            blocked.append({"url": url, "rule": rule})
    pages = len(seen) - 1
    sitemap_urls = {r.url for r in records if r.in_sitemap}
    in_sitemap = [b for b in blocked if b["url"] in sitemap_urls]
    details = {"status": status, "checked": pages, "blocked": _capped(blocked), "blocked_total": len(blocked),
               "in_sitemap": len(in_sitemap), "home_rule": home_rule}
    evidence = [f"{b['url']} ({b['rule']})" for b in blocked]
    if home_rule is not None:
        return _r("error", f"robots.txt blokkeert de homepage voor Googlebot ({home_rule}).",
                  [f"{home_url} ({home_rule})", *evidence], details)
    if pages and len(blocked) * 2 >= pages:
        return _r("error", f"robots.txt blokkeert {len(blocked)} van de {pages} pagina's voor Googlebot.",
                  evidence, details)
    if in_sitemap:
        return _r("warning", f"robots.txt blokkeert {len(in_sitemap)} pagina('s) die in de sitemap staan.",
                  [f"{b['url']} ({b['rule']})" for b in in_sitemap], details)
    extra = f" ({len(blocked)} pagina('s) buiten de sitemap wel geblokkeerd.)" if blocked else ""
    return _r("ok", f"robots.txt blokkeert de site niet voor Googlebot.{extra}", evidence, details)


def check_noindex(records: list[PageRecord]) -> dict[str, Any]:
    ok_pages = [r for r in records if r.status_code == 200 and not r.redirect_chain]
    if not ok_pages:
        return _r("unknown", "Geen bereikbare pagina's om te controleren.")
    noindex = [r for r in ok_pages if (r.indexability_reason or "").startswith("noindex")]
    home_noindex = next((r for r in noindex if _is_home(r)), None)
    in_sitemap = [r for r in noindex if r.in_sitemap]
    rows = [{"url": _page(r), "reason": r.indexability_reason, "in_sitemap": r.in_sitemap} for r in noindex]
    details = {"checked": len(ok_pages), "pages": _capped(rows), "total": len(noindex), "in_sitemap": len(in_sitemap)}
    evidence = [f"{r['url']} ({r['reason']})" for r in rows]
    if home_noindex is not None:
        return _r("error", f"De homepage staat op noindex ({home_noindex.indexability_reason}). In WordPress: "
                  "zet 'Zoekmachines ontmoedigen' uit.", evidence, details)
    if len(noindex) * 2 >= len(ok_pages):
        return _r("error", f"{len(noindex)} van de {len(ok_pages)} pagina's staan op noindex.", evidence, details)
    if in_sitemap:
        return _r("warning", f"{len(in_sitemap)} pagina('s) in de sitemap staan op noindex.",
                  [f"{_page(r)} ({r.indexability_reason})" for r in in_sitemap], details)
    if noindex:
        return _r("ok", f"Geen noindex op pagina's uit de sitemap; {len(noindex)} pagina('s) daarbuiten staan "
                  "bewust of onbewust op noindex (zie lijst).", evidence, details)
    return _r("ok", f"Geen noindex op de {len(ok_pages)} bereikbare pagina's.", details=details)


def check_sitemap(records: list[PageRecord], discovery: DiscoveryResult, base_url: str,
                  preferred_host: str, *, blocked: bool) -> dict[str, Any]:
    if not discovery.sitemaps:
        return _r("error", "Geen XML-sitemap gevonden (niet in robots.txt en niet op de standaardadressen).")
    in_robots = parse_robots_sitemaps(discovery.robots_txt or "", base_url)
    wrong = [u for u in discovery.urls
             if u.startswith("http://") or (urlparse(u).hostname or "") != preferred_host]
    not_ok = [] if blocked else [
        {"url": r.url, "status": r.status_code, "error": r.error}
        for r in records if r.in_sitemap and (r.error or r.status_code != 200)
    ]
    problems: list[str] = []
    if not in_robots:
        problems.append("de sitemap staat niet in robots.txt")
    if not discovery.urls:
        problems.append("de sitemap bevat geen URL's van deze site")
    if discovery.foreign_total:
        problems.append(f"{discovery.foreign_total} URL('s) op een ander domein")
    if wrong:
        problems.append(f"{len(wrong)} URL('s) via http:// of op een andere host dan {preferred_host}")
    if not_ok:
        problems.append(f"{len(not_ok)} URL('s) geven geen 200")
    details = {
        "sitemaps": _capped(discovery.sitemaps), "in_robots": in_robots, "urls": len(discovery.urls),
        "skipped_due_to_limit": discovery.skipped_due_to_limit,
        "foreign": discovery.foreign_sample, "foreign_total": discovery.foreign_total,
        "wrong_host": _capped(wrong), "wrong_host_total": len(wrong),
        "not_ok": _capped(not_ok), "not_ok_total": len(not_ok),
    }
    evidence = [*discovery.foreign_sample, *wrong, *(f"{row['url']} ({row['status'] or row['error']})" for row in not_ok)]
    if problems:
        return _r("warning", f"XML-sitemap gevonden, maar: {'; '.join(problems)}.", evidence, details)
    return _r("ok", f"XML-sitemap gevonden en in robots.txt, {len(discovery.urls)} URL's van {preferred_host}.",
              discovery.sitemaps, details)


def collect_test_refs(parsed: list[PageRecord], discovery: DiscoveryResult,
                      site: GoLiveSite) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """(verwijzingen gecapt, totaal, samenvatting per host)."""
    refs: list[dict[str, Any]] = []
    total = 0
    for rec in parsed:
        sig = _signals(rec)
        total += sig.get("test_refs_total", 0)
        refs.extend({"page": _page(rec), **item} for item in sig.get("test_refs") or [])
    for url in [*discovery.urls, *discovery.foreign_sample]:
        host = (urlparse(url).hostname or "").lower()
        if host in site.hosts or host == site.host:
            continue
        verdict = classify_host(urlparse(url).netloc, site)
        if verdict:
            total += 1
            refs.append({"page": "sitemap", "type": "sitemap", "url": url, "host": host,
                         "level": verdict[0], "reason": verdict[1]})
    hosts: dict[str, dict[str, Any]] = {}
    for ref in refs:
        entry = hosts.setdefault(ref["host"], {"host": ref["host"], "level": ref["level"], "reason": ref["reason"],
                                               "pages": set(), "types": set(), "refs": 0})
        entry["pages"].add(ref["page"])
        entry["types"].add(ref["type"])
        entry["refs"] += 1
    summary = [
        {**h, "pages": len(h["pages"]), "types": sorted(h["types"])}
        for h in sorted(hosts.values(), key=lambda h: (h["level"] != "error", -len(h["pages"]), h["host"]))
    ]
    return refs, total, summary


def check_staging_refs(parsed: list[PageRecord], discovery: DiscoveryResult, site: GoLiveSite) -> dict[str, Any]:
    refs, total, hosts = collect_test_refs(parsed, discovery, site)
    own = classify_host(site.host, site) if site.host else None
    details = {"hosts": hosts, "refs": _capped(refs), "total": total, "pages_checked": len(parsed),
               "site_is_test_host": bool(own)}
    if own:
        return _r("error", f"Het adres van de klant zelf is een testadres: {site.host} ({own[1]}). Zet de "
                  "website-URL van de klant op het live domein.", [site.host], details)
    evidence = [f"{h['host']} ({h['reason']}, {h['pages']} pagina('s))" for h in hosts]
    if any(r["level"] == "error" for r in refs):
        return _r("error", f"{total} verwijzing(en) naar de testomgeving op {len(hosts)} host(s).", evidence, details)
    if refs:
        return _r("warning", f"{total} verwijzing(en) naar een mogelijke testomgeving. Controleer of dit een "
                  "echte publieke site is.", evidence, details)
    return _r("ok", f"Geen verwijzingen naar een testomgeving gevonden op {len(parsed)} pagina's en in de sitemap.",
              details=details)


def check_pages_ok(records: list[PageRecord]) -> dict[str, Any]:
    failing = [r for r in records if r.error or r.final_status is None or r.final_status >= 400]
    broken_pages = [r for r in records if r.broken_links]
    broken = [{"page": _page(r), **link} for r in broken_pages for link in r.broken_links]
    details = {
        "checked": len(records),
        "failing": _capped([{"url": r.url, "status": r.final_status, "error": r.error} for r in failing]),
        "failing_total": len(failing),
        "broken": _capped(broken), "broken_total": len(broken), "broken_pages": len(broken_pages),
    }
    evidence = [f"{r.url} ({r.final_status or r.error})" for r in failing] + [
        f"{b['page']} → {b['url']} ({b['status'] or 'niet bereikbaar'})" for b in broken
    ]
    if failing or broken:
        parts = []
        if failing:
            parts.append(f"{len(failing)} van de {len(records)} pagina's geven een fout of zijn niet bereikbaar")
        if broken:
            parts.append(f"{len(broken)} kapotte interne link(s) op {len(broken_pages)} pagina('s)")
        return _r("error", f"{'; '.join(parts).capitalize()}.", evidence, details)
    return _r("ok", f"Alle {len(records)} pagina's bereikbaar, geen kapotte interne links.", details=details)


def check_staging_shielded(parsed: list[PageRecord], discovery: DiscoveryResult, site: GoLiveSite) -> dict[str, Any]:
    _refs, _total, hosts = collect_test_refs(parsed, discovery, site)
    instruction = ("Controleer dat de testomgeving offline is, achter een wachtwoord staat of naar de live site "
                   "doorverwijst: open het testadres in een privévenster.")
    if hosts:
        return _r("info", f"Gevonden testadressen: {', '.join(h['host'] for h in hosts[:5])}{_more(len(hosts), 5)}. "
                  f"{instruction}", [h["host"] for h in hosts], {"hosts": hosts})
    return _r("info", f"De scan vond geen testadres in de site. {instruction}", details={"hosts": []})


# --- tracking & cookies -----------------------------------------------------------

def check_tracking(parsed: list[PageRecord]) -> dict[str, Any]:
    if not parsed:
        return _r("unknown", "Geen HTML-pagina's om te controleren.")
    counts: Counter[str] = Counter()
    kinds: dict[str, str] = {}
    ua: set[str] = set()
    other: set[str] = set()
    missing: list[str] = []
    for rec in parsed:
        tracking = _signals(rec).get("tracking") or {}
        ids = [*tracking.get("gtm", []), *tracking.get("ga4", [])]
        for tid in tracking.get("gtm", []):
            kinds[tid] = "gtm"
        for tid in tracking.get("ga4", []):
            kinds[tid] = "ga4"
        counts.update(set(ids))
        ua.update(tracking.get("ua", []))
        other.update(tracking.get("other", []))
        if not ids:
            missing.append(_page(rec))
    n = len(parsed)
    ids = [{"id": tid, "kind": kinds[tid], "pages": c} for tid, c in counts.most_common()]
    gtm_ids = [i for i in ids if i["kind"] == "gtm"]
    details = {"pages_checked": n, "ids": ids, "ua": sorted(ua), "other": sorted(other),
               "missing": _capped(missing), "missing_total": len(missing)}
    evidence = [f"{i['id']}: {i['pages']} van {n} pagina's" for i in ids]
    if not ids:
        if ua:
            return _r("warning", f"Alleen een verouderde Universal Analytics-code ({', '.join(sorted(ua))}) gevonden "
                      f"in de HTML; die meet niet meer. GTM of GA4 niet gevonden in de HTML. {_TRACKING_NOTE}",
                      sorted(ua), details)
        found = f" Wel gevonden: {', '.join(sorted(other))}." if other else ""
        return _r("error", f"Trackingcode (GTM of GA4) niet gevonden in de HTML.{found} {_TRACKING_NOTE}",
                  details=details)
    problems = []
    if missing:
        problems.append(f"op {len(missing)} van de {n} pagina's geen GTM- of GA4-code gevonden in de HTML")
    if len(gtm_ids) > 1:
        problems.append(f"meerdere GTM-containers ({', '.join(i['id'] for i in gtm_ids)})")
    if not problems and ids[0]["pages"] < n:
        problems.append("geen enkele code staat op alle pagina's")
    if problems:
        return _r("warning", f"Trackingcode gevonden, maar {'; '.join(problems)}. {_TRACKING_NOTE}",
                  [*evidence, *missing], details)
    return _r("ok", f"{ids[0]['id']} staat op alle {n} pagina's.", evidence, details)


def check_consent(parsed: list[PageRecord]) -> dict[str, Any]:
    if not parsed:
        return _r("unknown", "Geen HTML-pagina's om te controleren.")
    counts: Counter[str] = Counter()
    for rec in parsed:
        counts.update(_signals(rec).get("consent") or [])
    tools = [{"name": name, "pages": c} for name, c in counts.most_common()]
    details = {"pages_checked": len(parsed), "tools": tools}
    note = "Controleer in een privévenster dat zonder toestemming geen marketing- en analysecookies worden geplaatst."
    if tools:
        names = ", ".join(t["name"] for t in tools)
        return _r("info", f"Cookiebanner gevonden: {names}. {note}",
                  [f"{t['name']}: {t['pages']} van {len(parsed)} pagina's" for t in tools], details)
    return _r("warning", "Geen bekende cookiebanner gevonden in de HTML. Een banner die via een tagmanager wordt "
              f"geladen, is voor deze scan onzichtbaar. {note}", details=details)


# --- basis ------------------------------------------------------------------------

def check_not_found(probes: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for probe in probes.get("not_found") or []:
        status = probe.get("final_status")
        if probe.get("error"):
            result, note = "unknown", probe["error"]
        elif status in (404, 410):
            result, note = "ok", f"geeft {status}"
        elif status == 200:
            result, note = "error", ("verwijst door naar een pagina met 200" if probe.get("chain")
                                     else "geeft 200 (zachte 404)")
        elif status in BLOCKED_STATUSES:
            result, note = "unknown", f"geeft {status} (scanner geblokkeerd?)"
        else:
            result, note = "warning", f"geeft {status}"
        rows.append({"url": probe["start"], "status": result, "note": note, "chain": probe.get("chain") or [],
                     "final_url": probe.get("final_url"), "final_status": status})
    if not rows:
        return _r("unknown", "De 404-controle is niet uitgevoerd.")
    statuses = [r["status"] for r in rows]
    if "error" in statuses:
        result, message = "error", "Een onbekende URL geeft geen echte 404: Google kan foutpagina's dan indexeren."
    elif all(s == "ok" for s in statuses):
        result, message = "ok", "Een onbekende URL geeft een echte 404."
    elif "warning" in statuses:
        result, message = "warning", "Een onbekende URL geeft een onverwachte statuscode."
    else:
        result, message = "unknown", "De 404-controle kon niet worden beoordeeld."
    return _r(result, message, [f"{r['url']}: {r['note']}" for r in rows], {"probes": rows})


def check_viewport(parsed: list[PageRecord]) -> dict[str, Any]:
    if not parsed:
        return _r("unknown", "Geen HTML-pagina's om te controleren.")
    missing = [r for r in parsed if not _signals(r).get("viewport_ok")]
    home_missing = any(_is_home(r) for r in missing)
    rows = [{"url": _page(r), "viewport": _signals(r).get("viewport")} for r in missing]
    details = {"pages_checked": len(parsed), "missing": _capped(rows), "missing_total": len(missing)}
    evidence = [f"{row['url']}" + (f" (viewport: {row['viewport']})" if row["viewport"] else "") for row in rows]
    if home_missing or len(missing) * 2 >= len(parsed) and missing:
        where = "de homepage" if home_missing else f"{len(missing)} van de {len(parsed)} pagina's"
        return _r("error", f"Geen viewport-meta met width=device-width op {where}.", evidence, details)
    if missing:
        return _r("warning", f"Geen viewport-meta met width=device-width op {len(missing)} pagina('s).",
                  evidence, details)
    return _r("ok", f"Viewport-meta op alle {len(parsed)} pagina's.", details=details)


def check_favicon(probes: dict[str, Any]) -> dict[str, Any]:
    candidates = probes.get("favicon") or []
    details = {"candidates": candidates}
    evidence = [f"{c['url']}: {c['status'] or c['error']} {c['content_type'] or ''}".strip() for c in candidates]
    ok = next((c for c in candidates if c["ok"]), None)
    if ok:
        return _r("ok", f"Favicon gevonden ({ok['url']}).", evidence, details)
    return _r("warning", "Geen favicon gevonden die als afbeelding laadt.", evidence, details)


def check_forms(parsed: list[PageRecord]) -> dict[str, Any]:
    pages = []
    for rec in parsed:
        sig = _signals(rec)
        if sig.get("forms_total"):
            pages.append({"url": _page(rec), "forms": sig["forms_total"], "actions": [f["action"] for f in sig["forms"]]})
    details = {"pages_checked": len(parsed), "pages": _capped(pages), "pages_total": len(pages)}
    instruction = ("Vul elk formulier op de live site in en verstuur het: controleer de bedankmelding en dat de "
                   "e-mail aankomt.")
    if pages:
        return _r("info", f"Formulieren op {len(pages)} pagina('s) (zoek- en winkelwagenformulieren niet "
                  f"meegeteld). {instruction}", [p["url"] for p in pages], details)
    return _r("info", "Geen formulieren gevonden in de HTML (formulieren die met JavaScript worden geladen, ziet "
              f"deze scan niet). {instruction}", details=details)


# --- alles samen ------------------------------------------------------------------

CONTENT_ITEMS = (
    "gl_mixed_content", "gl_internal_urls", "gl_noindex", "gl_staging_refs", "gl_pages_ok",
    "gl_tracking_installed", "gl_viewport", "gl_consent_banner", "gl_forms_tested",
)


def blocked_ratio(records: list[PageRecord]) -> tuple[int, int]:
    blocked = len([r for r in records if r.final_status in BLOCKED_STATUSES])
    return blocked, len(records)


def evaluate_golive(
    *,
    base_url: str,
    site: GoLiveSite,
    records: list[PageRecord],
    discovery: DiscoveryResult,
    probes: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """item_key → resultaat voor alle auto- en hybride punten."""
    parsed = [r for r in records if _signals(r) is not None]
    blocked, total = blocked_ratio(records)
    is_blocked = total > 0 and blocked * 2 > total
    origin = probes.get("origin") or origin_of(base_url) or base_url
    preferred_host = urlparse(origin).hostname or site.host
    home_url = f"{origin}/"

    items: dict[str, dict[str, Any]] = {
        "gl_https": check_https(probes),
        "gl_http_redirect": check_http_redirect(probes),
        "gl_host_variants": check_host_variants(probes, site),
        "gl_mixed_content": check_mixed_content(parsed),
        "gl_internal_urls": check_internal_urls(parsed, site),
        "gl_robots_open": check_robots(records, discovery, site, home_url),
        "gl_noindex": check_noindex(records),
        "gl_sitemap": check_sitemap(records, discovery, base_url, preferred_host, blocked=is_blocked),
        "gl_staging_refs": check_staging_refs(parsed, discovery, site),
        "gl_pages_ok": check_pages_ok(records),
        "gl_staging_shielded": check_staging_shielded(parsed, discovery, site),
        "gl_tracking_installed": check_tracking(parsed),
        "gl_consent_banner": check_consent(parsed),
        "gl_404": check_not_found(probes),
        "gl_viewport": check_viewport(parsed),
        "gl_favicon": check_favicon(probes),
        "gl_forms_tested": check_forms(parsed),
    }
    if not records:
        for key in CONTENT_ITEMS:
            items[key] = _r("unknown", "Geen pagina's gevonden om te controleren.")
    elif is_blocked:
        for key in CONTENT_ITEMS:
            items[key] = _r("unknown", _blocked_message(blocked, total), details=items[key].get("details"))
    # Hybride punten nooit 'ok' (vangnet; de checks hierboven geven het al niet).
    for key, result in items.items():
        if ITEMS[key].mode == "hybrid" and result["status"] == "ok":
            result["status"] = "info"
    return {key: items[key] for key in ITEMS if key in items}


def build_golive_payload(
    *,
    base_url: str,
    site: GoLiveSite,
    records: list[PageRecord],
    discovery: DiscoveryResult,
    probes: dict[str, Any],
) -> dict[str, Any]:
    items = evaluate_golive(base_url=base_url, site=site, records=records, discovery=discovery, probes=probes)
    blocked, total = blocked_ratio(records)
    return {
        "items": items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "auto_status": dict(Counter(r.get("status") for r in items.values())),
            "pages": total,
            "pages_parsed": len([r for r in records if _signals(r) is not None]),
            "blocked_pages": blocked,
            "discovery_source": "sitemap" if discovery.urls else "crawl",
            "origin": probes.get("origin"),
        },
    }
