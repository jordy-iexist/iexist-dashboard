"""Core Web Vitals per pagina via de Google PageSpeed Insights API (v5)."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
MAX_ATTEMPTS = 3

# Google-drempels: (goed tot en met, slecht vanaf)
THRESHOLDS: dict[str, tuple[float, float]] = {
    "lcp": (2500, 4000),
    "cls": (0.1, 0.25),
    "inp": (200, 500),
    "tbt": (200, 600),
    "fcp": (1800, 3000),
    "ttfb": (800, 1800),
}

_FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "lcp",
    "INTERACTION_TO_NEXT_PAINT": "inp",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
    "FIRST_CONTENTFUL_PAINT_MS": "fcp",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb",
}
_CATEGORY_MAP = {"FAST": "good", "AVERAGE": "needs_improvement", "SLOW": "poor"}


def rate(metric: str, value: float | None) -> str | None:
    if value is None or metric not in THRESHOLDS:
        return None
    good, poor = THRESHOLDS[metric]
    if value <= good:
        return "good"
    if value > poor:
        return "poor"
    return "needs_improvement"


def _worst(ratings: list[str | None]) -> str | None:
    present = [r for r in ratings if r]
    if not present:
        return None
    for level in ("poor", "needs_improvement", "good"):
        if level in present:
            return level
    return None


def _audit_value(audits: dict[str, Any], key: str) -> float | None:
    value = (audits.get(key) or {}).get("numericValue")
    return float(value) if isinstance(value, (int, float)) else None


def parse_psi_response(payload: dict[str, Any]) -> dict[str, Any]:
    lighthouse = payload.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}
    perf_score = ((lighthouse.get("categories") or {}).get("performance") or {}).get("score")

    lab = {
        "lcp": _audit_value(audits, "largest-contentful-paint"),
        "cls": _audit_value(audits, "cumulative-layout-shift"),
        "tbt": _audit_value(audits, "total-blocking-time"),
        "fcp": _audit_value(audits, "first-contentful-paint"),
        "si": _audit_value(audits, "speed-index"),
        "ttfb": _audit_value(audits, "server-response-time"),
        "performance_score": round(perf_score * 100) if isinstance(perf_score, (int, float)) else None,
    }
    lab_status = _worst([rate("lcp", lab["lcp"]), rate("cls", lab["cls"]), rate("tbt", lab["tbt"])])

    field: dict[str, Any] | None = None
    experience = payload.get("loadingExperience") or {}
    metrics = experience.get("metrics") or {}
    if metrics:
        field = {"origin_fallback": bool(experience.get("origin_fallback"))}
        for api_key, short in _FIELD_METRICS.items():
            metric = metrics.get(api_key)
            if not metric:
                continue
            value = metric.get("percentile")
            if short == "cls" and isinstance(value, (int, float)):
                value = value / 100  # API levert CLS x100
            field[short] = {
                "value": value,
                "rating": _CATEGORY_MAP.get(str(metric.get("category") or "").upper()),
            }
        field["overall"] = _CATEGORY_MAP.get(str(experience.get("overall_category") or "").upper())

    # Velddata van de pagina zelf (geen origin-fallback) is leidend, anders lab.
    if field and not field["origin_fallback"] and field.get("overall"):
        status, source = field["overall"], "field"
    else:
        status, source = lab_status, "lab"

    return {"lab": lab, "field": field, "status": status, "source": source, "strategy": "mobile"}


async def _measure_one(
    client: httpx.AsyncClient, url: str, api_key: str
) -> tuple[dict[str, Any] | None, str | None]:
    params = {"url": url, "strategy": "mobile", "category": "performance", "key": api_key}
    last_error = "Onbekende fout"
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.get(PSI_ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            last_error = f"PSI niet bereikbaar: {exc.__class__.__name__}"
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if response.status_code == 200:
            return parse_psi_response(response.json()), None
        try:
            message = (response.json().get("error") or {}).get("message") or response.text[:200]
        except ValueError:
            message = response.text[:200]
        last_error = f"PSI {response.status_code}: {message}"
        if response.status_code in {429, 500, 502, 503, 504}:
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break  # 400 (bijv. pagina niet laadbaar) heeft geen zin om te herhalen
    return None, last_error


async def measure_vitals(
    urls: list[str],
    *,
    api_key: str,
    concurrency: int,
    on_result: Callable[[str, dict[str, Any] | None, str | None], bool],
) -> None:
    """Meet elke URL; `on_result` geeft False terug om te stoppen."""
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async with httpx.AsyncClient(timeout=120.0) as client:

        async def _one(url: str) -> None:
            if stop.is_set():
                return
            async with sem:
                if stop.is_set():
                    return
                data, error = await _measure_one(client, url, api_key)
                if not on_result(url, data, error):
                    stop.set()

        await asyncio.gather(*(_one(u) for u in urls))
