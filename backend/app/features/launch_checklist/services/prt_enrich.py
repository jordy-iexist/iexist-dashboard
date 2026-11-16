"""ProRankTracker-data (AI-zichtbaarheid) voor een fase 1-, 2- of 4-scan.

Zoekt de site van de klant tussen de URL's die in ProRankTracker in AI-tracking
staan en slaat de cijfers op (`LaunchScan.proranktracker`): score, appearances,
mentions en links per platform en per prompt. Antwoordteksten en bronnen worden
niet bewaard; die haalt `prompt_detail` live op als iemand een prompt opent.

De snapshot heeft altijd een `state`:

- `ok`: de site wordt getrackt en de cijfers zijn opgehaald;
- `not_configured`: er staat geen API-token in de configuratie;
- `not_tracked`: de koppeling werkt, maar deze site staat niet in AI-tracking
  (voor de meeste klanten de gewone situatie);
- `error`: ProRankTracker gaf een fout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urldefrag

import httpx

from app.features.launch_checklist.services.ahrefs_enrich import target_of
from app.services.proranktracker import client as prt
from app.services.proranktracker.client import ProRankTrackerServiceError

# Grok staat ook in het rapport, maar is niet te tracken en altijd leeg.
PLATFORMS = ("aio", "aim", "chatgpt", "copilot", "gemini", "perplexity")
PLATFORM_LABELS: dict[str, str] = {
    "aio": "AI Overviews",
    "aim": "AI Mode",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "copilot": "Copilot",
    "perplexity": "Perplexity",
}
# Volgorde in de UI: eerst Google, dan de chatbots.
DETAIL_ORDER = ("aio", "aim", "chatgpt", "gemini", "copilot", "perplexity")
# `engine` in de promptrecords → platformsleutel.
ENGINE_KEYS: dict[str, str] = {
    "aio": "aio", "aim": "aim", "chatgpt": "chatgpt",
    "copilot": "copilot", "gemini": "gemini", "perplexity": "perplexity",
}
TRACKED_STATUSES = {"shown", "not_shown"}
# Positie 101 (of een tekst als "NTH") betekent: niet gevonden.
NOT_FOUND_RANK = 101
LINK_KINDS = {"is_link": "link", "is_citation": "citation"}

STATE_MESSAGES: dict[str, str] = {
    "not_configured": "ProRankTracker is niet gekoppeld: PRORANKTRACKER_API_X_TOKEN ontbreekt in de "
                      "backend-configuratie.",
    "not_tracked": "Deze site wordt niet getrackt in ProRankTracker (AI-tracking). Voeg de site en prompts "
                   "toe in ProRankTracker om de AI-zichtbaarheid te meten.",
}


# --- hulpfuncties ---------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(url: Any) -> str:
    """Host zonder `www.`, ook voor een URL zonder schema."""
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return target_of(text)


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _count(value: Any) -> int:
    return _int(value) or 0


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rank(value: Any) -> int | None:
    """Positie in het antwoord; 101 of een niet-numerieke waarde = niet gevonden."""
    rank = _int(value)
    if rank is None or rank <= 0 or rank >= NOT_FOUND_RANK:
        return None
    return rank


def _status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in TRACKED_STATUSES else "not_added"


# --- site ------------------------------------------------------------------------------

def resolve_url(base_url: str, urls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """De getrackte URL met dezelfde host als de klant (schema en `www.` tellen niet mee).

    Exacte host-match: een subdomein of een domein dat de host alleen bevat telt niet.
    """
    host = _host(base_url)
    if not host:
        return None
    for entry in urls:
        if isinstance(entry, dict) and _int(entry.get("url_id")) is not None and _host(entry.get("url")) == host:
            return entry
    return None


# --- snapshot --------------------------------------------------------------------------

def empty_snapshot(state: str, message: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "message": message or STATE_MESSAGES.get(state),
        "fetched_at": _now_iso(),
        "url_id": None,
        "url": None,
        "totals": None,
        "platforms": None,
        "prompts": [],
        "errors": [],
    }


def _prompt(row: dict[str, Any]) -> dict[str, Any] | None:
    prompt_id = _int(row.get("prompt_id"))
    if prompt_id is None:
        return None
    platforms = _dict(row.get("platforms"))
    trend = row.get("trend") if isinstance(row.get("trend"), list) else []
    return {
        "prompt_id": prompt_id,
        "prompt": str(row.get("prompt") or ""),
        "location": row.get("location") or None,
        "lang": row.get("lang") or None,
        "visibility": _num(row.get("visibility")),
        "appearances": _count(row.get("appearances")),
        "mentions": _count(row.get("mentions")),
        "links": _count(row.get("links")),
        "platforms": {
            p: {
                "status": _status(_dict(platforms.get(p)).get("status")),
                "count": _count(_dict(platforms.get(p)).get("count")),
            }
            for p in PLATFORMS
        },
        "trend": [n for n in (_num(v) for v in trend) if n is not None],
    }


def build_snapshot(entry: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Snapshot uit het rapport van één URL (`reports/ai/ai-visibility?url_id=`)."""
    url_id = _int(entry.get("url_id"))
    rows = next(
        (u for u in report.get("urls") or [] if isinstance(u, dict) and _int(u.get("url_id")) == url_id),
        None,
    )
    if rows is None:
        urls = [u for u in report.get("urls") or [] if isinstance(u, dict)]
        rows = urls[0] if len(urls) == 1 else {}
    prompts = [p for p in (_prompt(r) for r in rows.get("prompts") or [] if isinstance(r, dict)) if p]

    cards = _dict(report.get("summary_cards"))
    appearances, mentions = _dict(cards.get("appearances")), _dict(cards.get("mentions"))
    links, visibility = _dict(cards.get("links")), _dict(cards.get("visibility"))

    platforms: dict[str, dict[str, Any]] = {}
    for p in PLATFORMS:
        tracked = sum(1 for prompt in prompts if prompt["platforms"][p]["status"] in TRACKED_STATUSES)
        shown = sum(1 for prompt in prompts if prompt["platforms"][p]["status"] == "shown")
        link_card = _dict(_dict(links.get("platforms")).get(p))
        platforms[p] = {
            # Zonder getrackte prompts is er geen score: None, niet 0.
            "visibility": _num(_dict(visibility.get("platforms")).get(p)) if tracked else None,
            "appearances": _count(_dict(appearances.get("platforms")).get(p)),
            "mentions": _count(_dict(mentions.get("platforms")).get(p)),
            "links": _count(link_card.get("count")),
            "links_avg": _num(link_card.get("avg")),
            "prompts_tracked": tracked,
            "prompts_shown": shown,
        }

    snapshot = empty_snapshot("ok")
    snapshot.update(
        message=None,
        url_id=url_id,
        url=str(entry.get("url") or rows.get("url") or "") or None,
        totals={
            "visibility": _num(visibility.get("value")),
            "appearances": _count(appearances.get("value")),
            "mentions": _count(mentions.get("value")),
            "links": _count(links.get("value")),
            "links_avg": _num(links.get("average")),
            "prompts": len(prompts),
        },
        platforms=platforms,
        prompts=prompts,
    )
    return snapshot


def collect(base_url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Snapshot voor één klant, inclusief de gevallen zonder token of zonder tracking.

    Twee calls: de lijst met getrackte URL's en het rapport van de gevonden URL.
    Deze functie gooit geen fouten van ProRankTracker; `client` is alleen voor tests.
    """
    if not prt.is_configured():
        return empty_snapshot("not_configured")
    try:
        overview = prt.visibility_report(client=client)
        entry = resolve_url(base_url, [u for u in overview.get("urls") or [] if isinstance(u, dict)])
        if entry is None:
            return empty_snapshot("not_tracked")
        report = prt.visibility_report(_int(entry.get("url_id")), client=client)
        return build_snapshot(entry, report)
    except ProRankTrackerServiceError as exc:
        if exc.code == "not_configured":
            return empty_snapshot("not_configured")
        snapshot = empty_snapshot("error", f"ProRankTracker-data niet opgehaald: {exc}")
        snapshot["errors"].append(str(exc))
        return snapshot
    except (AttributeError, KeyError, TypeError, ValueError) as exc:  # onverwachte vorm van het antwoord
        snapshot = empty_snapshot("error", "Onverwacht antwoord van ProRankTracker.")
        snapshot["errors"].append(f"{type(exc).__name__}: {exc}"[:300])
        return snapshot


# --- promptdetail (live) ---------------------------------------------------------------

def _mentions(record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {"rank": None, "total": 0, "counts": {}, "items": []}
    ai = _dict(record.get("ai"))
    counts = {str(brand): _count(n) for brand, n in _dict(ai.get("count")).items()}
    items = [
        {"brand": str(item.get("b") or ""), "sentence": str(item.get("s") or "")}
        for item in ai.get("full") or [] if isinstance(item, dict)
    ]
    return {"rank": _rank(record.get("rank")), "total": _count(ai.get("total")), "counts": counts, "items": items}


def _link_item(item: dict[str, Any], own_host: str) -> dict[str, Any]:
    raw = str(item.get("url") or "")
    url, fragment = urldefrag(raw)
    kind = LINK_KINDS.get(fragment)
    if kind is None:
        url = raw  # onbekend fragment: de URL ongewijzigd laten
    return {
        "url": url,
        "title": item.get("title") or None,
        "rank": _rank(item.get("rank")),
        "kind": kind,
        "checked_at": item.get("checkdatetime") or None,
        "is_own": bool(own_host) and _host(url) == own_host,
    }


def _links(record: dict[str, Any] | None, own_host: str) -> dict[str, Any]:
    if record is None:
        return {"rank": None, "total": 0, "items": []}
    ai = _dict(record.get("ai"))
    items = [_link_item(item, own_host) for item in ai.get("full") or [] if isinstance(item, dict)]
    return {"rank": _rank(record.get("rank")), "total": _count(ai.get("total")), "items": items}


def _belongs_to(record: dict[str, Any], prompt_id: int, prompt: str) -> bool:
    """`ai.visibility_id` is het `prompt_id` uit het rapport; zonder id telt de prompttekst."""
    visibility_id = _dict(record.get("ai")).get("visibility_id")
    if visibility_id not in (None, ""):
        return _int(visibility_id) == prompt_id
    return str(record.get("name") or "").strip() == prompt.strip()


def find_prompt(snapshot: Any, prompt_id: int) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict) or snapshot.get("state") != "ok" or _int(snapshot.get("url_id")) is None:
        return None
    return next(
        (p for p in snapshot.get("prompts") or [] if isinstance(p, dict) and _int(p.get("prompt_id")) == prompt_id),
        None,
    )


def prompt_detail(snapshot: Any, prompt_id: int, *, client: httpx.Client | None = None) -> dict[str, Any] | None:
    """Actueel antwoord per platform voor één prompt uit de snapshot van een scan.

    None als de snapshot niet `ok` is of de prompt er niet in staat. Fouten van
    ProRankTracker gaan als `ProRankTrackerServiceError` door naar de aanroeper.
    """
    prompt = find_prompt(snapshot, prompt_id)
    if prompt is None:
        return None
    url_id = _int(snapshot.get("url_id"))
    text = str(prompt.get("prompt") or "")
    records = prt.prompt_records(url_id, text, client=client)

    by_platform: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        platform = ENGINE_KEYS.get(str(record.get("engine") or "").strip().lower())
        ai_type = str(record.get("ai_type") or "").strip().lower()
        if platform is None or ai_type not in {"mentions", "links"} or not _belongs_to(record, prompt_id, text):
            continue
        by_platform.setdefault(platform, {}).setdefault(ai_type, record)

    own_host = _host(snapshot.get("url"))
    platforms = []
    for p in DETAIL_ORDER:
        found = by_platform.get(p, {})
        mention_record, link_record = found.get("mentions"), found.get("links")
        answer = None
        for record in (link_record, mention_record):
            text_value = _dict((record or {}).get("ai")).get("answer_text")
            if text_value:
                answer = str(text_value)
                break
        platforms.append({
            "platform": p,
            "label": PLATFORM_LABELS[p],
            "tracked": bool(found),
            "mentions": _mentions(mention_record),
            "links": _links(link_record, own_host),
            "answer_text": answer,
        })
    return {
        "prompt_id": prompt_id,
        "prompt": text,
        "url": snapshot.get("url"),
        "fetched_at": _now_iso(),
        "platforms": platforms,
    }
