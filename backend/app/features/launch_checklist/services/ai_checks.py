"""AI-vindbaarheidschecks: robots.txt voor AI-bots, llms.txt, schema, SSR."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.url_guard import is_safe_external_url
from app.features.launch_checklist.services.discovery import USER_AGENT, url_key
from app.features.launch_checklist.services.inventory import PageRecord

AI_BOTS: list[tuple[str, str]] = [
    ("GPTBot", "OpenAI (training)"),
    ("OAI-SearchBot", "ChatGPT Search"),
    ("ChatGPT-User", "ChatGPT (live browsen)"),
    ("ClaudeBot", "Anthropic (training)"),
    ("Claude-SearchBot", "Claude Search"),
    ("Claude-User", "Claude (live browsen)"),
    ("PerplexityBot", "Perplexity"),
    ("Google-Extended", "Google Gemini / AI"),
    ("Applebot-Extended", "Apple Intelligence"),
    ("CCBot", "Common Crawl"),
    ("Bingbot", "Bing / Copilot"),
    ("Googlebot", "Google Search"),
]
# Bots die zoek-/antwoordverkeer opleveren; blokkeren is een echt probleem.
SEARCH_BOTS = {"OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Bingbot", "Googlebot"}
ORG_SCHEMA_TYPES = {"Organization", "LocalBusiness", "Corporation", "ProfessionalService", "Store", "Restaurant"}
SSR_MIN_WORDS = 150


def _check(key: str, label: str, status: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "message": message, "details": details}


def _fetch_text(url: str) -> tuple[int | None, str, str]:
    if not is_safe_external_url(url):
        return None, "", ""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=15.0, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError:
        return None, "", ""
    return resp.status_code, resp.headers.get("content-type", ""), resp.text[:100_000]


def run_ai_checks(
    *,
    base_url: str,
    robots_txt: str | None,
    robots_status: int | None,
    sitemaps: list[str],
    records: list[PageRecord],
) -> dict[str, Any]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    checks: list[dict[str, Any]] = []

    # robots.txt
    bots: list[dict[str, Any]] = []
    if robots_txt is None:
        checks.append(_check(
            "robots_txt", "robots.txt", "warning",
            "Geen robots.txt gevonden" + (f" (status {robots_status})." if robots_status else "."),
        ))
        bots = [{"bot": b, "label": label, "allowed": True} for b, label in AI_BOTS]
    else:
        rp = RobotFileParser()
        rp.parse(robots_txt.splitlines())
        for bot, label in AI_BOTS:
            bots.append({"bot": bot, "label": label, "allowed": rp.can_fetch(bot, f"{origin}/")})
        checks.append(_check("robots_txt", "robots.txt", "ok", "robots.txt is aanwezig."))

    blocked = [b for b in bots if not b["allowed"]]
    blocked_search = [b["bot"] for b in blocked if b["bot"] in SEARCH_BOTS]
    if blocked_search:
        checks.append(_check(
            "ai_bots_blocked", "AI-zoekbots", "error",
            f"robots.txt blokkeert zoek-/antwoordbots: {', '.join(blocked_search)}.",
            {"blocked": blocked_search},
        ))
    elif blocked:
        checks.append(_check(
            "ai_bots_blocked", "AI-zoekbots", "warning",
            f"Alleen trainingsbots geblokkeerd: {', '.join(b['bot'] for b in blocked)}. Zoekbots hebben toegang.",
            {"blocked": [b["bot"] for b in blocked]},
        ))
    else:
        checks.append(_check("ai_bots_blocked", "AI-zoekbots", "ok", "Alle AI-bots hebben toegang tot de homepage."))

    # Sitemap
    declared = bool(robots_txt and "sitemap:" in robots_txt.lower())
    if not sitemaps:
        checks.append(_check("sitemap", "XML-sitemap", "error", "Geen bruikbare XML-sitemap gevonden."))
    elif not declared:
        checks.append(_check(
            "sitemap", "XML-sitemap", "warning",
            "Sitemap gevonden, maar niet vermeld in robots.txt.", {"sitemaps": sitemaps[:10]},
        ))
    else:
        checks.append(_check("sitemap", "XML-sitemap", "ok", "Sitemap staat in robots.txt.", {"sitemaps": sitemaps[:10]}))

    # llms.txt
    status, content_type, body = _fetch_text(f"{origin}/llms.txt")
    if status == 200 and "html" not in content_type.lower() and body.strip():
        checks.append(_check("llms_txt", "llms.txt", "ok", "llms.txt is aanwezig.", {"preview": body[:500]}))
    else:
        checks.append(_check(
            "llms_txt", "llms.txt", "warning",
            "Geen llms.txt gevonden. Hiermee geef je AI-assistenten een samenvatting van de belangrijkste pagina's.",
        ))

    # Schema / structured data
    html_pages = [r for r in records if r.is_html and r.final_status == 200 and not r.redirect_chain]
    if not html_pages:
        checks.append(_check(
            "page_access", "Pagina's bereikbaar", "error",
            "Geen enkele HTML-pagina kon worden opgehaald; schema- en contentchecks zijn overgeslagen.",
        ))
        return _finish(checks, bots)
    with_schema = [r for r in html_pages if r.schema_types]
    coverage = round(100 * len(with_schema) / len(html_pages)) if html_pages else 0
    all_types: dict[str, int] = {}
    for r in with_schema:
        for t in r.schema_types:
            all_types[t] = all_types.get(t, 0) + 1
    schema_status = "ok" if coverage >= 80 else "warning" if coverage >= 30 else "error"
    checks.append(_check(
        "schema_coverage", "Structured data", schema_status,
        f"{coverage}% van de pagina's heeft JSON-LD structured data.",
        {"coverage": coverage, "types": dict(sorted(all_types.items(), key=lambda kv: -kv[1])[:15])},
    ))

    home = next(
        (r for r in html_pages if url_key(r.final_url or r.url) == url_key(origin + "/")),
        html_pages[0],
    )
    if home is not None:
        home_types = set(home.schema_types)
        if home_types & ORG_SCHEMA_TYPES:
            checks.append(_check("org_schema", "Organisatie-schema", "ok", "Homepage bevat Organization/LocalBusiness-schema."))
        else:
            checks.append(_check(
                "org_schema", "Organisatie-schema", "warning",
                "Homepage mist Organization/LocalBusiness-schema (belangrijk voor entiteitsherkenning door AI).",
            ))
        if "WebSite" not in home_types:
            checks.append(_check("website_schema", "WebSite-schema", "warning", "Homepage mist WebSite-schema."))
        else:
            checks.append(_check("website_schema", "WebSite-schema", "ok", "WebSite-schema aanwezig."))

        words = home.word_count or 0
        if home.is_html and home.final_status == 200 and words < SSR_MIN_WORDS:
            checks.append(_check(
                "ssr_content", "Content zonder JavaScript", "warning",
                f"De homepage heeft maar {words} woorden in de ruwe HTML. Content wordt mogelijk pas met JavaScript geladen, en veel AI-crawlers voeren geen JS uit.",
                {"word_count": words},
            ))
        else:
            checks.append(_check(
                "ssr_content", "Content zonder JavaScript", "ok",
                f"Homepage heeft {words} woorden in de server-HTML.", {"word_count": words},
            ))

    return _finish(checks, bots)


def _finish(checks: list[dict[str, Any]], bots: list[dict[str, Any]]) -> dict[str, Any]:
    score_map = {"ok": 1.0, "warning": 0.5, "error": 0.0}
    score = round(100 * sum(score_map[c["status"]] for c in checks) / len(checks)) if checks else 0
    return {"score": score, "checks": checks, "bots": bots}
