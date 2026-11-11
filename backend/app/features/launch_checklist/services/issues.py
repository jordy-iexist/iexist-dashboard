"""Deterministische regels die scanresultaten omzetten naar actiepunten.

Elke regel krijgt de pagina's (+ ai_checks) en levert issue-dicts op. Nieuwe
regels toevoegen = functie schrijven en in RULES zetten. Elk issue is los
genoeg om later als Monday-item door te zetten.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable

from app.db.models import LaunchScanPage
from app.features.launch_checklist.services.pagespeed import rate

TITLE_MIN, TITLE_MAX = 30, 60
META_MIN, META_MAX = 70, 160
THIN_CONTENT_WORDS = 300
SLOW_RESPONSE_MS = 5000
SLOW_TTFB_MS = 1000

Issue = dict[str, Any]
Rule = Callable[[list[LaunchScanPage], dict[str, Any]], Iterable[Issue]]

# Labels per issue_type (voor UI-groepering en Monday later).
ISSUE_TYPES: dict[str, dict[str, str]] = {
    "fetch_error": {"label": "Pagina niet bereikbaar", "category": "techniek"},
    "status_4xx": {"label": "Pagina geeft 4xx-fout", "category": "techniek"},
    "status_5xx": {"label": "Pagina geeft serverfout (5xx)", "category": "techniek"},
    "redirect_in_sitemap": {"label": "Redirect in sitemap", "category": "techniek"},
    "redirect_chain": {"label": "Redirectketen", "category": "techniek"},
    "noindex_in_sitemap": {"label": "Noindex-pagina in sitemap", "category": "techniek"},
    "canonical_mismatch": {"label": "Canonical wijst naar andere URL", "category": "techniek"},
    "broken_links": {"label": "Kapotte interne links", "category": "techniek"},
    "slow_response": {"label": "Trage serverrespons", "category": "performance"},
    "title_missing": {"label": "Title ontbreekt", "category": "on-page"},
    "title_too_long": {"label": "Title te lang", "category": "on-page"},
    "title_too_short": {"label": "Title te kort", "category": "on-page"},
    "title_duplicate": {"label": "Dubbele title", "category": "on-page"},
    "meta_missing": {"label": "Meta description ontbreekt", "category": "on-page"},
    "meta_too_long": {"label": "Meta description te lang", "category": "on-page"},
    "meta_too_short": {"label": "Meta description te kort", "category": "on-page"},
    "meta_duplicate": {"label": "Dubbele meta description", "category": "on-page"},
    "h1_missing": {"label": "H1 ontbreekt", "category": "on-page"},
    "h1_multiple": {"label": "Meerdere H1's", "category": "on-page"},
    "h1_duplicate": {"label": "Dubbele H1 over pagina's", "category": "on-page"},
    "images_missing_alt": {"label": "Afbeeldingen zonder alt-tekst", "category": "content"},
    "thin_content": {"label": "Weinig content", "category": "content"},
    "lang_missing": {"label": "lang-attribuut ontbreekt", "category": "techniek"},
    "cwv_lcp": {"label": "LCP te traag", "category": "performance"},
    "cwv_cls": {"label": "CLS te hoog", "category": "performance"},
    "cwv_inp": {"label": "INP/TBT te hoog", "category": "performance"},
    "ai_robots_txt": {"label": "robots.txt ontbreekt", "category": "ai"},
    "ai_ai_bots_blocked": {"label": "AI-bots geblokkeerd", "category": "ai"},
    "ai_sitemap": {"label": "Sitemap-probleem", "category": "ai"},
    "ai_llms_txt": {"label": "llms.txt ontbreekt", "category": "ai"},
    "ai_schema_coverage": {"label": "Weinig structured data", "category": "ai"},
    "ai_org_schema": {"label": "Organisatie-schema ontbreekt", "category": "ai"},
    "ai_website_schema": {"label": "WebSite-schema ontbreekt", "category": "ai"},
    "ai_ssr_content": {"label": "Content afhankelijk van JavaScript", "category": "ai"},
    "ai_page_access": {"label": "Pagina's niet bereikbaar voor crawlers", "category": "ai"},
}


def _issue(
    issue_type: str,
    severity: str,
    *,
    page: LaunchScanPage | None,
    title: str,
    description: str,
    recommendation: str,
    details: Any = None,
) -> Issue:
    return {
        "issue_type": issue_type,
        "category": ISSUE_TYPES.get(issue_type, {}).get("category", "techniek"),
        "severity": severity,
        "page_id": page.id if page is not None else None,
        "url": page.url if page is not None else None,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "details": details,
    }


def final_status(page: LaunchScanPage) -> int | None:
    chain = page.redirect_chain or []
    if chain and isinstance(chain[-1], dict) and chain[-1].get("final"):
        return chain[-1].get("status")
    return page.status_code


def redirect_hops(page: LaunchScanPage) -> int:
    return len([h for h in (page.redirect_chain or []) if not (isinstance(h, dict) and h.get("final"))])


def _is_ok_html(page: LaunchScanPage) -> bool:
    return (
        page.status_code == 200
        and not page.redirect_chain
        and "html" in (page.content_type or "").lower()
    )


def _is_indexable_html(page: LaunchScanPage) -> bool:
    return _is_ok_html(page) and page.indexable is True


# --- regels ---------------------------------------------------------------

def rule_status(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        if p.error and p.status_code is None:
            yield _issue(
                "fetch_error", "hoog", page=p,
                title=f"Pagina niet bereikbaar: {p.path}",
                description=f"De pagina kon niet worden opgehaald ({p.error}).",
                recommendation="Controleer of de URL bestaat en de server/firewall de crawler niet blokkeert.",
            )
            continue
        status = final_status(p)
        if status is None:
            continue
        if 400 <= status < 500:
            yield _issue(
                "status_4xx", "hoog", page=p,
                title=f"{status}-fout op {p.path}",
                description=f"De pagina geeft statuscode {status}" + (" en staat in de sitemap." if p.in_sitemap else "."),
                recommendation="Herstel de pagina of zet een 301-redirect naar de juiste pagina en haal hem uit de sitemap.",
                details={"status": status},
            )
        elif status >= 500:
            yield _issue(
                "status_5xx", "hoog", page=p,
                title=f"Serverfout ({status}) op {p.path}",
                description=f"De server geeft statuscode {status}.",
                recommendation="Laat de developer/hosting de serverfout onderzoeken.",
                details={"status": status},
            )


def rule_redirects(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        hops = redirect_hops(p)
        if not hops:
            continue
        if p.in_sitemap:
            yield _issue(
                "redirect_in_sitemap", "middel", page=p,
                title=f"Redirect in sitemap: {p.path}",
                description=f"De sitemap bevat een URL die doorverwijst naar {p.final_url}.",
                recommendation="Vervang de URL in de sitemap door de eind-URL.",
                details={"chain": p.redirect_chain},
            )
        if hops > 1:
            yield _issue(
                "redirect_chain", "middel", page=p,
                title=f"Redirectketen ({hops} stappen) op {p.path}",
                description=f"De URL gaat via {hops} redirects naar {p.final_url}.",
                recommendation="Laat de eerste redirect direct naar de eind-URL wijzen.",
                details={"chain": p.redirect_chain},
            )


def rule_indexability(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        reason = p.indexability_reason or ""
        if "noindex" in reason and p.in_sitemap:
            yield _issue(
                "noindex_in_sitemap", "middel", page=p,
                title=f"Noindex-pagina in sitemap: {p.path}",
                description=f"De pagina staat in de sitemap maar heeft {reason}.",
                recommendation="Haal de noindex weg als de pagina gevonden moet worden, anders uit de sitemap halen.",
            )
        if reason == "Canonical naar andere URL":
            yield _issue(
                "canonical_mismatch", "middel", page=p,
                title=f"Canonical wijst naar andere URL: {p.path}",
                description=f"De canonical verwijst naar {p.canonical}.",
                recommendation="Controleer of dit bewust is; anders de canonical naar de pagina zelf laten wijzen.",
                details={"canonical": p.canonical},
            )


def rule_onpage(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        if not _is_indexable_html(p):
            continue
        # Title
        if not p.title:
            yield _issue(
                "title_missing", "hoog", page=p,
                title=f"Title ontbreekt op {p.path}",
                description="De pagina heeft geen <title>.",
                recommendation=f"Schrijf een unieke title van {TITLE_MIN}–{TITLE_MAX} tekens met het belangrijkste zoekwoord.",
            )
        elif (p.title_length or 0) > TITLE_MAX:
            yield _issue(
                "title_too_long", "laag", page=p,
                title=f"Title te lang ({p.title_length} tekens) op {p.path}",
                description=f"\"{p.title}\" wordt waarschijnlijk afgekapt in Google.",
                recommendation=f"Kort de title in tot maximaal {TITLE_MAX} tekens.",
                details={"title": p.title, "length": p.title_length},
            )
        elif (p.title_length or 0) < TITLE_MIN:
            yield _issue(
                "title_too_short", "laag", page=p,
                title=f"Title te kort ({p.title_length} tekens) op {p.path}",
                description=f"\"{p.title}\" benut de ruimte in de zoekresultaten niet.",
                recommendation=f"Breid de title uit naar {TITLE_MIN}–{TITLE_MAX} tekens.",
                details={"title": p.title, "length": p.title_length},
            )
        # Meta description
        if not p.meta_description:
            yield _issue(
                "meta_missing", "middel", page=p,
                title=f"Meta description ontbreekt op {p.path}",
                description="De pagina heeft geen meta description.",
                recommendation=f"Schrijf een wervende meta description van {META_MIN}–{META_MAX} tekens.",
            )
        elif (p.meta_description_length or 0) > META_MAX:
            yield _issue(
                "meta_too_long", "laag", page=p,
                title=f"Meta description te lang ({p.meta_description_length} tekens) op {p.path}",
                description="De meta description wordt afgekapt in Google.",
                recommendation=f"Kort in tot maximaal {META_MAX} tekens.",
                details={"meta_description": p.meta_description, "length": p.meta_description_length},
            )
        elif (p.meta_description_length or 0) < META_MIN:
            yield _issue(
                "meta_too_short", "laag", page=p,
                title=f"Meta description te kort ({p.meta_description_length} tekens) op {p.path}",
                description="De meta description is erg kort.",
                recommendation=f"Breid uit naar {META_MIN}–{META_MAX} tekens.",
                details={"meta_description": p.meta_description, "length": p.meta_description_length},
            )
        # H1
        h1_count = p.h1_count or 0
        if h1_count == 0:
            yield _issue(
                "h1_missing", "hoog", page=p,
                title=f"H1 ontbreekt op {p.path}",
                description="De pagina heeft geen H1-kop.",
                recommendation="Voeg één duidelijke H1 toe die het onderwerp van de pagina beschrijft.",
            )
        elif h1_count > 1:
            yield _issue(
                "h1_multiple", "middel", page=p,
                title=f"{h1_count} H1's op {p.path}",
                description=f"De pagina heeft {h1_count} H1-koppen.",
                recommendation="Houd één H1 over en maak de rest H2/H3.",
                details={"h1": p.h1},
            )
        # Content
        if (p.word_count or 0) < THIN_CONTENT_WORDS:
            yield _issue(
                "thin_content", "laag", page=p,
                title=f"Weinig content ({p.word_count or 0} woorden) op {p.path}",
                description=f"De pagina heeft minder dan {THIN_CONTENT_WORDS} woorden in de HTML.",
                recommendation="Breid de content uit of voeg de pagina samen met een verwante pagina.",
                details={"word_count": p.word_count},
            )
        if (p.images_missing_alt or 0) > 0:
            yield _issue(
                "images_missing_alt", "middel" if (p.images_missing_alt or 0) >= 5 else "laag", page=p,
                title=f"{p.images_missing_alt} afbeelding(en) zonder alt op {p.path}",
                description=f"{p.images_missing_alt} van de {p.images_total} afbeeldingen hebben geen alt-attribuut.",
                recommendation="Geef elke inhoudelijke afbeelding een beschrijvende alt-tekst (decoratief: alt=\"\").",
                details={"missing": p.images_missing_alt, "total": p.images_total},
            )


def rule_duplicates(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    indexable = [p for p in pages if _is_indexable_html(p)]
    specs = [
        ("title_duplicate", "middel", lambda p: (p.title or "").strip().lower(), "title",
         "Meerdere pagina's hebben dezelfde title.", "Maak de title per pagina uniek."),
        ("meta_duplicate", "laag", lambda p: (p.meta_description or "").strip().lower(), "meta description",
         "Meerdere pagina's hebben dezelfde meta description.", "Schrijf per pagina een unieke meta description."),
        ("h1_duplicate", "laag", lambda p: ((p.h1 or [""])[0] or "").strip().lower() if (p.h1_count or 0) else "", "H1",
         "Meerdere pagina's hebben dezelfde H1.", "Maak de H1 per pagina uniek."),
    ]
    for issue_type, severity, key_fn, label, desc, rec in specs:
        groups: dict[str, list[LaunchScanPage]] = defaultdict(list)
        for p in indexable:
            key = key_fn(p)
            if key:
                groups[key].append(p)
        for group in groups.values():
            if len(group) < 2:
                continue
            for p in group:
                others = [o.url for o in group if o.id != p.id]
                yield _issue(
                    issue_type, severity, page=p,
                    title=f"Dubbele {label} op {p.path}",
                    description=f"{desc} Deze {label} komt ook voor op {len(others)} andere pagina('s).",
                    recommendation=rec,
                    details={"value": key_fn(p), "duplicates": others[:20]},
                )


def rule_links_and_speed(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        broken = p.broken_links or []
        if broken:
            yield _issue(
                "broken_links", "hoog", page=p,
                title=f"{len(broken)} kapotte link(s) op {p.path}",
                description="De pagina linkt naar interne URL's die een fout geven.",
                recommendation="Pas de links aan naar werkende pagina's of zet redirects.",
                details={"links": broken},
            )
        if not _is_ok_html(p):
            continue
        # Voorkeur: TTFB uit PageSpeed (Google meet los van onze scanbelasting).
        lab_ttfb = ((p.cwv or {}).get("lab") or {}).get("ttfb")
        if isinstance(lab_ttfb, (int, float)):
            if lab_ttfb > SLOW_TTFB_MS:
                yield _issue(
                    "slow_response", "middel", page=p,
                    title=f"Trage serverrespons (TTFB {int(lab_ttfb)} ms) op {p.path}",
                    description=f"Google meet een server-responstijd van {int(lab_ttfb)} ms (doel: < 600 ms).",
                    recommendation="Controleer page caching/CDN, PHP-workers en hosting.",
                    details={"ttfb_ms": lab_ttfb, "source": "pagespeed"},
                )
        elif (p.response_time_ms or 0) > SLOW_RESPONSE_MS:
            yield _issue(
                "slow_response", "laag", page=p,
                title=f"Trage serverrespons ({p.response_time_ms} ms) op {p.path}",
                description=f"Tijdens de scan duurde het {p.response_time_ms} ms om de HTML te leveren (gemeten onder scanbelasting).",
                recommendation="Controleer caching (page cache/CDN) en hosting.",
                details={"response_time_ms": p.response_time_ms, "source": "scan"},
            )


def rule_lang(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    missing = [p for p in pages if _is_indexable_html(p) and not p.lang]
    if missing:
        yield _issue(
            "lang_missing", "laag", page=None,
            title=f"lang-attribuut ontbreekt op {len(missing)} pagina('s)",
            description="Het <html>-element heeft geen lang-attribuut.",
            recommendation="Stel <html lang=\"nl\"> (of de juiste taal) in het thema in.",
            details={"urls": [p.url for p in missing[:50]]},
        )


def rule_vitals(pages: list[LaunchScanPage], _: dict[str, Any]) -> Iterable[Issue]:
    for p in pages:
        cwv = p.cwv or {}
        if not cwv:
            continue
        lab = cwv.get("lab") or {}
        field = cwv.get("field") or {}
        use_field = bool(field) and not field.get("origin_fallback")

        def metric(name: str) -> tuple[float | None, str | None, str]:
            if use_field and isinstance(field.get(name), dict):
                return field[name].get("value"), field[name].get("rating"), "veld"
            return None, None, "lab"

        # LCP
        value, rating, src = metric("lcp")
        if rating is None:
            value, rating, src = lab.get("lcp"), rate("lcp", lab.get("lcp")), "lab"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_lcp", "hoog" if rating == "poor" else "middel", page=p,
                title=f"LCP {value / 1000:.1f}s op {p.path}",
                description=f"Largest Contentful Paint is {value / 1000:.1f}s ({src}data, mobiel). Doel: ≤ 2,5s.",
                recommendation="Optimaliseer de hero-afbeelding (formaat/WebP/preload), verminder render-blocking CSS/JS en verbeter de serverrespons.",
                details={"value": value, "rating": rating, "source": src},
            )
        # CLS
        value, rating, src = metric("cls")
        if rating is None:
            value, rating, src = lab.get("cls"), rate("cls", lab.get("cls")), "lab"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_cls", "hoog" if rating == "poor" else "middel", page=p,
                title=f"CLS {value:.2f} op {p.path}",
                description=f"Cumulative Layout Shift is {value:.2f} ({src}data, mobiel). Doel: ≤ 0,1.",
                recommendation="Geef afbeeldingen/embeds vaste afmetingen, reserveer ruimte voor banners en laad fonts met font-display.",
                details={"value": value, "rating": rating, "source": src},
            )
        # INP (veld) of TBT (lab)
        value, rating, src = metric("inp")
        label = "INP"
        if rating is None:
            value, rating, src, label = lab.get("tbt"), rate("tbt", lab.get("tbt")), "lab", "TBT"
        if rating in {"poor", "needs_improvement"} and value is not None:
            yield _issue(
                "cwv_inp", "hoog" if rating == "poor" else "middel", page=p,
                title=f"{label} {int(value)} ms op {p.path}",
                description=f"{label} is {int(value)} ms ({src}data, mobiel). Doel: {'≤ 200 ms' if label == 'INP' else '≤ 200 ms TBT'}.",
                recommendation="Verminder en splits JavaScript (plugins, trackers, sliders), stel scripts uit en vermijd lange taken.",
                details={"value": value, "rating": rating, "source": src, "metric": label},
            )


_AI_RECOMMENDATIONS = {
    "robots_txt": "Plaats een robots.txt met een verwijzing naar de sitemap.",
    "ai_bots_blocked": "Pas robots.txt aan zodat in elk geval de AI-zoekbots (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, PerplexityBot) toegang hebben.",
    "sitemap": "Zorg voor een XML-sitemap en vermeld die in robots.txt (Sitemap: https://…/sitemap.xml).",
    "llms_txt": "Voeg een /llms.txt toe met een korte beschrijving van het bedrijf en links naar de belangrijkste pagina's.",
    "schema_coverage": "Voeg JSON-LD toe (Organization, WebPage, Service/Product, FAQ, BreadcrumbList) via het SEO-plugin/thema.",
    "org_schema": "Voeg Organization- of LocalBusiness-schema met NAW, logo en sameAs-profielen toe aan de homepage.",
    "website_schema": "Voeg WebSite-schema toe aan de homepage.",
    "page_access": "Controleer firewall/bot-protectie (Cloudflare, Shopify, Wordfence): crawlers moeten de pagina's kunnen ophalen.",
    "ssr_content": "Zorg dat de belangrijkste content server-side in de HTML staat (geen client-only rendering).",
}


def rule_ai(_: list[LaunchScanPage], ctx: dict[str, Any]) -> Iterable[Issue]:
    for check in (ctx.get("ai_checks") or {}).get("checks", []):
        if check.get("status") == "ok":
            continue
        key = check.get("key", "")
        yield _issue(
            f"ai_{key}", "hoog" if check.get("status") == "error" else "middel", page=None,
            title=f"{check.get('label')}: {check.get('message')}",
            description=check.get("message") or "",
            recommendation=_AI_RECOMMENDATIONS.get(key, ""),
            details=check.get("details"),
        )


RULES: list[Rule] = [
    rule_status,
    rule_redirects,
    rule_indexability,
    rule_onpage,
    rule_duplicates,
    rule_links_and_speed,
    rule_lang,
    rule_vitals,
    rule_ai,
]


def generate_issues(pages: list[LaunchScanPage], ai_checks: dict[str, Any] | None) -> list[Issue]:
    ctx = {"ai_checks": ai_checks or {}}
    issues: list[Issue] = []
    for rule in RULES:
        issues.extend(rule(pages, ctx))
    return issues
