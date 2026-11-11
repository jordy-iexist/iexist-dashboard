"""Test of de CDN/hosting (o.a. Cloudflare) AI-bots blokkeert, los van robots.txt.

We halen een paar pagina's op met een gewone browser-UA en met de user-agents
van AI-crawlers. Een 403/429/503 of challenge-pagina bij de bot terwijl de
browser wél 200 krijgt, wijst op een blokkade. IP-gebaseerde blokkades (echte
bots komen van eigen IP-ranges) kunnen we zo niet zien.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.url_guard import is_safe_external_url

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_BOT_PREFIX = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
# Googlebot/Bingbot testen we bewust niet: CDN's blokkeren nep-Googlebots
# (verkeerd IP) en dat zou een vals alarm geven.
BOT_USER_AGENTS: list[tuple[str, str, str]] = [
    ("GPTBot", "OpenAI (training)", _BOT_PREFIX + "GPTBot/1.2; +https://openai.com/gptbot)"),
    ("OAI-SearchBot", "ChatGPT Search", _BOT_PREFIX + "OAI-SearchBot/1.0; +https://openai.com/searchbot)"),
    ("ChatGPT-User", "ChatGPT (live browsen)", _BOT_PREFIX + "ChatGPT-User/1.0; +https://openai.com/bot)"),
    ("ClaudeBot", "Anthropic (training)", _BOT_PREFIX + "ClaudeBot/1.0; +claudebot@anthropic.com)"),
    ("Claude-SearchBot", "Claude Search", _BOT_PREFIX + "Claude-SearchBot/1.0; +https://www.anthropic.com)"),
    ("Claude-User", "Claude (live browsen)", _BOT_PREFIX + "Claude-User/1.0; +https://www.anthropic.com)"),
    ("PerplexityBot", "Perplexity", _BOT_PREFIX + "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"),
    ("Perplexity-User", "Perplexity (live)", _BOT_PREFIX + "Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)"),
    ("CCBot", "Common Crawl", "CCBot/2.0 (https://commoncrawl.org/faq/)"),
]
SEARCH_BOTS = {"OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User"}
_BLOCK_STATUSES = {401, 403, 406, 429, 503}
_CHALLENGE_MARKERS = ("just a moment...", "attention required", "cf-chl", "challenge-platform",
                      "captcha", "access denied", "request blocked", "sucuri website firewall")


def _cdn_from_headers(headers: httpx.Headers) -> str | None:
    server = headers.get("server", "").lower()
    if "cloudflare" in server or headers.get("cf-ray"):
        return "Cloudflare"
    if headers.get("x-sucuri-id") or "sucuri" in server:
        return "Sucuri"
    if "akamai" in server or headers.get("x-akamai-transformed"):
        return "Akamai"
    if headers.get("x-vercel-id"):
        return "Vercel"
    if headers.get("x-served-by", "").lower().startswith("cache-") or "fastly" in headers.get("via", "").lower():
        return "Fastly"
    if "bunny" in server:
        return "BunnyCDN"
    if headers.get("x-shopid") or headers.get("x-shopify-stage"):
        return "Shopify"
    if headers.get("x-kinsta-cache"):
        return "Kinsta"
    if headers.get("x-ah-environment") or "wp engine" in headers.get("x-powered-by", "").lower():
        return "WP Engine"
    return None


def _fetch(client: httpx.Client, url: str, ua: str) -> dict[str, Any]:
    if not is_safe_external_url(url):
        return {"status": None, "blocked": False, "error": "onveilige URL"}
    try:
        resp = client.get(url, headers={"User-Agent": ua, "Accept": "text/html,*/*;q=0.8"})
    except httpx.HTTPError as exc:
        return {"status": None, "blocked": False, "error": exc.__class__.__name__}
    body = resp.text[:20_000].lower() if "html" in resp.headers.get("content-type", "") else ""
    challenge = bool(resp.headers.get("cf-mitigated")) or (
        resp.status_code != 200 and any(m in body for m in _CHALLENGE_MARKERS)
    ) or ("just a moment..." in body[:3000])
    return {
        "status": resp.status_code,
        "blocked": resp.status_code in _BLOCK_STATUSES or challenge,
        "challenge": challenge,
        "length": len(resp.content),
        "cdn": _cdn_from_headers(resp.headers),
    }


def test_bot_access(urls: list[str]) -> dict[str, Any]:
    urls = [u for u in urls if u][:4]
    result: dict[str, Any] = {"urls": urls, "cdn": None, "baseline_ok": False, "bots": [], "note":
                              "Alleen user-agent-blokkades zijn te detecteren; IP-gebaseerde blokkades niet."}
    if not urls:
        return result
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        baseline = {u: _fetch(client, u, BROWSER_UA) for u in urls}
        ok_urls = [u for u, r in baseline.items() if r.get("status") == 200 and not r.get("blocked")]
        result["cdn"] = next((r.get("cdn") for r in baseline.values() if r.get("cdn")), None)
        result["baseline"] = {u: r.get("status") for u, r in baseline.items()}
        result["baseline_ok"] = bool(ok_urls)
        if not ok_urls:
            return result
        for bot, label, ua in BOT_USER_AGENTS:
            checks = {u: _fetch(client, u, ua) for u in ok_urls}
            blocked_urls = [u for u, r in checks.items() if r.get("blocked")]
            result["bots"].append({
                "bot": bot,
                "label": label,
                "search_bot": bot in SEARCH_BOTS,
                "blocked": bool(blocked_urls),
                "statuses": {u: r.get("status") for u, r in checks.items()},
                "challenge": any(r.get("challenge") for r in checks.values()),
            })
    return result
