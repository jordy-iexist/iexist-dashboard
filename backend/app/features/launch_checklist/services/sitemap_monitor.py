"""Dagelijkse sitemap-monitor: sitemap vergelijken met de vorige stand.

Pure logica (geen netwerk), zodat de vangrails los te testen zijn. De worker
(`worker/sitemap_monitor.py`) haalt de sitemap op, laat `plan_run` bepalen wat
er gescand moet worden en schrijft daarna de snapshot bij.

Snapshot (`LaunchSitemapSnapshot.entries`): `{url_key: {"url": ..., "lastmod": ... | None}}`.
Recente wijzigingen: lijst `{"kind": "new" | "changed" | "removed", "url", "lastmod",
"detected_at"}`, nieuwste eerst, begrensd op MAX_RECENT_CHANGES.

Vangrails:
- Eerste run (nog geen stand): alleen de uitgangssituatie vastleggen, niets scannen.
- Lege of onbereikbare sitemap: fout melden, de vorige stand blijft staan (anders
  lijkt alles "verwijderd").
- Een kind-sitemap mislukt (`failed_sitemaps`) of de sitemap is afgekapt: wel nieuw
  en gewijzigd verwerken, maar geen verwijderingen (een tijdelijk kapotte
  kind-sitemap zou morgen anders honderden "nieuwe" pagina's opleveren).
- Plafond per run: wat erboven valt wordt niet in de stand bijgewerkt en komt dus
  de volgende dag vanzelf aan de beurt.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.db.models import LaunchScan, LaunchScanIssue
from app.features.launch_checklist.services.content_checks import F1_META_TYPES
from app.features.launch_checklist.services.discovery import DiscoveryResult, url_key
from app.features.launch_checklist.services.golive_checklist import MONITOR_PHASE

MAX_RECENT_CHANGES = 300
CHANGE_KINDS = ("new", "changed", "removed")

# Fase-3-punten die hetzelfde dekken als fase-1-punten (zelfde koppeling als
# `c3_meta_fixed` gebruikt): staat het c3-punt er, dan vervalt het fase-1-punt.
C3_COVERS_F1: dict[str, frozenset[str]] = {
    "c3_meta_title": frozenset(t for t in F1_META_TYPES if t.startswith("title_")),
    "c3_meta_description": frozenset(t for t in F1_META_TYPES if t.startswith("meta_")),
}

Entries = dict[str, dict[str, Any]]


def diff_sitemap(
    entries: Entries, discovered_urls: Iterable[str], lastmod: dict[str, str] | None
) -> dict[str, list[dict[str, Any]]]:
    """Verschil tussen de vorige stand en de gevonden URL's, op `url_key`.

    - new: in de sitemap, niet in de vorige stand;
    - changed: in beide, en beide kanten hebben een lastmod die verschilt;
    - removed: in de vorige stand, niet meer in de sitemap.

    Elk element is `{"key", "url", "lastmod"}`; bij `changed` ook `previous_lastmod`.
    Volgorde: die van de sitemap (nieuw/gewijzigd) en van de vorige stand (verwijderd).
    """
    lastmod = lastmod or {}
    new: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in discovered_urls:
        key = url_key(url)
        if key in seen:
            continue
        seen.add(key)
        current = lastmod.get(key)
        before = entries.get(key)
        if before is None:
            new.append({"key": key, "url": url, "lastmod": current})
            continue
        previous = before.get("lastmod")
        if current and previous and current != previous:
            changed.append({"key": key, "url": url, "lastmod": current, "previous_lastmod": previous})
    removed = [
        {"key": key, "url": value.get("url") or key, "lastmod": value.get("lastmod")}
        for key, value in entries.items()
        if key not in seen
    ]
    return {"new": new, "changed": changed, "removed": removed}


@dataclass
class MonitorPlan:
    """Wat een run moet doen.

    `kind`:
    - "error": sitemap leeg/onbereikbaar; alleen `error` vastleggen, stand ongemoeid;
    - "baseline": eerste run; `entries` is de uitgangssituatie, niets scannen;
    - "unchanged": geen nieuwe, gewijzigde of verwijderde pagina's;
    - "changes": `targets` scannen en/of `removed` verwerken.

    `entries` is de nieuwe stand, ervan uitgaande dat `targets` en `removed`
    verwerkt worden. Mislukt de run, dan blijft de oude stand staan.
    """

    kind: str
    entries: Entries = field(default_factory=dict)
    targets: list[dict[str, Any]] = field(default_factory=list)  # nieuw + gewijzigd, binnen het plafond
    deferred: list[dict[str, Any]] = field(default_factory=list)  # boven het plafond: morgen
    removed: list[dict[str, Any]] = field(default_factory=list)
    removals_skipped: int = 0  # verwijderingen niet verwerkt (mislukte/afgekapte sitemap)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Deels mislukte of afgekapte sitemap: wordt `last_error` van de snapshot, ook al is
    # de run verder gelukt (verwijderingen zijn dan niet verwerkt).
    sitemap_problem: str | None = None

    @property
    def new_count(self) -> int:
        return sum(1 for t in self.targets if t["kind"] == "new")

    @property
    def changed_count(self) -> int:
        return sum(1 for t in self.targets if t["kind"] == "changed")


def _entry(url: str, lastmod: str | None) -> dict[str, Any]:
    return {"url": url, "lastmod": lastmod}


def plan_run(entries: Entries | None, discovery: DiscoveryResult, *, max_pages: int) -> MonitorPlan:
    """Bepaal met de vangrails wat deze run scant en hoe de stand daarna is.

    `entries` is None of leeg als er nog geen uitgangssituatie is.
    """
    if not discovery.urls:
        if not discovery.sitemaps:
            error = "Geen bereikbare sitemap gevonden; de vorige stand is bewaard."
        else:
            error = "De sitemap bevat geen pagina's; de vorige stand is bewaard."
        return MonitorPlan(kind="error", entries=dict(entries or {}), error=error)

    current: Entries = {}
    for url in discovery.urls:
        key = url_key(url)
        current.setdefault(key, _entry(url, discovery.lastmod.get(key)))

    problems: list[str] = []
    if discovery.failed_sitemaps:
        failed = discovery.failed_sitemaps
        problems.append(
            f"{len(failed)} sitemap(s) niet opgehaald of niet te lezen "
            f"({', '.join(failed[:3])}{', …' if len(failed) > 3 else ''})."
        )
    if discovery.skipped_due_to_limit:
        problems.append(
            f"De sitemap bevat {discovery.skipped_due_to_limit} URL's meer dan het maximum "
            "(SITEMAP_MONITOR_MAX_URLS)."
        )

    if not entries:
        # Uitgangssituatie, ook bij een deels mislukte sitemap (anders start de monitor nooit
        # bij een kind-sitemap die blijvend stuk is); de fout wordt wel gemeld.
        return MonitorPlan(kind="baseline", entries=current, sitemap_problem=" ".join(problems) or None)

    warnings: list[str] = []
    diff = diff_sitemap(entries, discovery.urls, discovery.lastmod)
    # Nieuw eerst (sitemapvolgorde), dan gewijzigd op de opgeslagen (oude) lastmod, oudste eerst.
    # Een uitgestelde pagina houdt zijn oude lastmod en schuift zo vanzelf naar voren, ook als
    # de sitemap elke dag andere lastmods geeft (lastmod = generatietijd, voorraadwijzigingen).
    changed = sorted(diff["changed"], key=lambda t: str(t.get("previous_lastmod") or ""))
    candidates = [{**t, "kind": "new"} for t in diff["new"]] + [{**t, "kind": "changed"} for t in changed]
    limit = max(0, int(max_pages))
    targets, deferred = candidates[:limit], candidates[limit:]
    if deferred:
        warnings.append(
            f"{len(candidates)} nieuwe of gewijzigde pagina's gevonden; er worden er {len(targets)} per run "
            f"gescand (SITEMAP_MONITOR_MAX_PAGES_PER_RUN). De overige {len(deferred)} volgen bij de volgende run."
        )

    removed = diff["removed"]
    removals_skipped = 0
    if problems:
        # Een deel van de sitemap ontbreekt: ontbrekende pagina's zijn dan niet echt verwijderd.
        removals_skipped = len(removed)
        removed = []
        problems.append(
            f"{removals_skipped} ontbrekende pagina's zijn niet als verwijderd gemeld."
            if removals_skipped else "Verwijderde pagina's worden in deze run niet gemeld."
        )
        warnings.extend(problems)

    # Nieuwe stand: alles wat nu in de sitemap staat (ook lastmod-updates zonder "wijziging"),
    # behalve wat boven het plafond valt; verwijderingen die niet verwerkt worden blijven staan.
    new_entries: Entries = {}
    deferred_keys = {t["key"] for t in deferred}
    for key, value in current.items():
        if key in deferred_keys:
            if key in entries:
                new_entries[key] = dict(entries[key])  # gewijzigd maar uitgesteld: oude lastmod houden
            continue  # nieuw maar uitgesteld: morgen weer "nieuw"
        new_entries[key] = value
    if removals_skipped:
        for key, value in entries.items():
            if key not in current:
                new_entries[key] = dict(value)

    kind = "changes" if (targets or removed) else "unchanged"
    return MonitorPlan(
        kind=kind,
        entries=new_entries,
        targets=targets,
        deferred=deferred,
        removed=removed,
        removals_skipped=removals_skipped,
        warnings=warnings,
        sitemap_problem=" ".join(problems) or None,
    )


def retry_later(plan: MonitorPlan, previous: Entries, keys: set[str]) -> MonitorPlan:
    """Plan zonder de doelen in `keys`: die zijn niet echt gescand (ophaalfout of blokkade).

    Ze gaan net als een uitgestelde pagina terug naar de vorige stand: een gewijzigde
    pagina houdt zijn oude lastmod, een nieuwe pagina verdwijnt uit de stand. Zo komen
    ze bij de volgende run opnieuw aan bod, en tellen ze niet als wijziging.
    """
    if not keys:
        return plan
    entries = dict(plan.entries)
    for key in keys:
        if key in previous:
            entries[key] = dict(previous[key])
        else:
            entries.pop(key, None)
    return replace(
        plan,
        entries=entries,
        targets=[t for t in plan.targets if t["key"] not in keys],
        deferred=[*plan.deferred, *[t for t in plan.targets if t["key"] in keys]],
    )


def change_items(plan: MonitorPlan, detected_at: datetime) -> list[dict[str, Any]]:
    """Regels voor `recent_changes` van een verwerkte run (nieuw, gewijzigd, verwijderd)."""
    stamp = detected_at.isoformat()
    items = [
        {"kind": t["kind"], "url": t["url"], "lastmod": t.get("lastmod"), "detected_at": stamp}
        for t in plan.targets
    ]
    items += [
        {"kind": "removed", "url": r["url"], "lastmod": r.get("lastmod"), "detected_at": stamp}
        for r in plan.removed
    ]
    return items


def merge_recent_changes(
    previous: list[dict[str, Any]] | None, new_items: list[dict[str, Any]], limit: int = MAX_RECENT_CHANGES
) -> list[dict[str, Any]]:
    """Nieuwe wijzigingen vooraan, begrensd op `limit`."""
    return [*new_items, *[i for i in (previous or []) if isinstance(i, dict)]][:limit]


def snapshot_summary(entries: Entries | None) -> dict[str, Any]:
    """Aantal URL's in de stand en of de sitemap lastmod-waarden geeft."""
    entries = entries or {}
    return {
        "total_urls": len(entries),
        "has_lastmod": any((v or {}).get("lastmod") for v in entries.values()),
    }


def drop_covered_f1_issues(
    f1_issues: list[dict[str, Any]], c3_issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fase-1-punten weglaten die een c3-punt op dezelfde pagina al dekt (meta title/description)."""
    covered: set[tuple[str | None, str]] = set()
    for issue in c3_issues:
        for f1_type in C3_COVERS_F1.get(issue["issue_type"], ()):
            covered.add((issue.get("page_id"), f1_type))
    return [i for i in f1_issues if (i.get("page_id"), i["issue_type"]) not in covered]


# --- database: de monitor-scan van een klant ----------------------------------

def monitor_scan(db: Session, customer_id: str) -> LaunchScan | None:
    """De doorlopende monitor-scan (phase = 6) van de klant; de nieuwste als er meer zijn."""
    return (
        db.query(LaunchScan)
        .filter(LaunchScan.customer_website_id == customer_id, LaunchScan.phase == MONITOR_PHASE)
        .order_by(LaunchScan.created_at.desc())
        .first()
    )


def open_issue_count(db: Session, scan_id: str | None) -> int:
    if not scan_id:
        return 0
    return (
        db.query(LaunchScanIssue)
        .filter(LaunchScanIssue.scan_id == scan_id, LaunchScanIssue.status == "open")
        .count()
    )


# --- lock per klant (Redis) -----------------------------------------------------------
# Voorkomt twee runs tegelijk voor dezelfde klant (dagelijkse run plus "Nu controleren",
# of twee klikken). "Nu controleren" pakt de lock al vóór het inplannen, zodat ook een
# run die nog in de wachtrij staat een tweede klik tegenhoudt (409).

LOCK_KEY = "launch:sitemap-monitor:lock:{customer_id}"
# Ruim boven de harde tijdslimiet van de taak (1800 s): een gecrashte worker laat de lock
# vanzelf los, een lopende run raakt hem niet kwijt.
LOCK_TTL_SECONDS = 3600
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def acquire_lock(customer_id: str, token: str | None = None) -> str | None:
    """Pak de lock (of bevestig dat `token` hem al heeft). Geeft het token, of None als bezet."""
    client = get_redis()
    key = LOCK_KEY.format(customer_id=customer_id)
    token = token or uuid.uuid4().hex
    if client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
        return token
    if client.get(key) == token:  # al van ons (gepakt door "Nu controleren"): verlengen
        client.expire(key, LOCK_TTL_SECONDS)
        return token
    return None


def release_lock(customer_id: str, token: str) -> None:
    """Geef de lock vrij, alleen als hij nog van ons is."""
    get_redis().eval(_RELEASE_SCRIPT, 1, LOCK_KEY.format(customer_id=customer_id), token)
