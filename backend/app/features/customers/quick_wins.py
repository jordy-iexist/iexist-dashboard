"""Quick wins van een klant uit Ahrefs: zoekwoorden op positie 4–20, per klant bewaard.

Haalt via `site-explorer/organic-keywords` de zoekwoorden op positie 4–20 op (hoogste volume
eerst, maximaal `AHREFS_QUICK_WINS_LIMIT`), zet ze om en bewaart ze in `customer_quick_wins`.
Een bezoek gebruikt de bewaarde stand; die wordt pas opnieuw opgehaald als hij ouder is dan
`AHREFS_QUICK_WINS_TTL_DAYS`, als er nog niets is, of als het domein of land is gewijzigd.
De knop "Vernieuwen" (`refresh`) haalt altijd opnieuw op. Ophalen kost 24 units per rij.

Het antwoord heeft altijd een `state`:

- `ok`: er is een stand (eventueel met een waarschuwing in `message`, bijv. als vernieuwen mislukte);
- `not_configured`: er staat geen Ahrefs-API-key in de configuratie (er wordt niets aangeroepen);
- `error`: ophalen mislukte en er is geen eerdere stand, of de klant heeft geen website-adres.

De endpoints gebruiken `load_merged`/`refresh_merged`: die voegen de bewaarde Ahrefs-rijen samen
met de zoekwoorden die in ProRankTracker gevolgd worden (live opgehaald, niet bewaard; zie
`merge` en `combine`). Elke rij krijgt dan een `source`: "prt", "ahrefs" of "both".

De functies committen niet; de aanroeper (router) is eigenaar van de transactie.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import CustomerQuickWins, CustomerWebsite
from app.features.customers.rankings import STATE_MESSAGES, host_of, keyword_key, organic_rows, position
from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

# Positiebereik van een quick win.
POSITION_MIN, POSITION_MAX = 4, 20
# Vergelijkingsperiode voor de trend (`delta`).
COMPARE_DAYS = 30

# Kans-regel: "hoog" bij positie t/m HOOG_MAX_POSITION én KD t/m HOOG_MAX_KD, mits er
# zoekvolume is; "laag" vanaf LAAG_MIN_POSITION of bij een KD boven LAAG_ABOVE_KD; anders
# "middel".
HOOG_MAX_POSITION = 10
HOOG_MAX_KD = 30
LAAG_MIN_POSITION = 16
LAAG_ABOVE_KD = 60

MESSAGES: dict[str, str] = {
    "not_configured": "Ahrefs is niet gekoppeld: AHREFS_API_KEY ontbreekt in de backend-configuratie.",
    "no_url": "Deze klant heeft geen website-adres, dus er kunnen geen quick wins uit Ahrefs worden "
              "opgehaald.",
    "not_fetched": "Er zijn nog geen quick wins opgehaald voor dit domein. Klik op Vernieuwen om ze "
                   "uit Ahrefs op te halen.",
}


# --- omzetten --------------------------------------------------------------------------

def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def kans(position: int, kd: int | None, volume: int | None) -> str:
    """Kans op een snelle verbetering: "hoog", "middel" of "laag".

    Zonder KD telt alleen de positie: vanaf LAAG_MIN_POSITION "laag", anders "middel".
    Zonder zoekvolume (0 of onbekend) wordt een zoekwoord nooit "hoog": er valt dan
    weinig te winnen, hoe makkelijk de positie ook te verbeteren is.
    """
    has_volume = volume is not None and volume > 0
    if has_volume and kd is not None and position <= HOOG_MAX_POSITION and kd <= HOOG_MAX_KD:
        return "hoog"
    if position >= LAAG_MIN_POSITION or (kd is not None and kd > LAAG_ABOVE_KD):
        return "laag"
    return "middel"


def to_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Eén Ahrefs-rij omzetten; `None` zonder zoekwoord of zonder positie binnen 4–20.

    `delta` is positief bij een stijging (Ahrefs' `best_position_diff` is het omgekeerde).
    """
    keyword = _text(raw.get("keyword"))
    position = _int(raw.get("best_position"))
    if keyword is None or position is None or not POSITION_MIN <= position <= POSITION_MAX:
        return None
    diff = _int(raw.get("best_position_diff"))
    volume = _int(raw.get("volume"))
    kd = _int(raw.get("keyword_difficulty"))
    return {
        "keyword": keyword,
        "position": position,
        "delta": -diff if diff is not None else None,
        "volume": volume if volume is not None and volume >= 0 else None,
        "kd": kd,
        "url": _text(raw.get("best_position_url")),
        "kans": kans(position, kd, volume),
    }


def convert(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alle rijen omzetten, in de volgorde van Ahrefs (volume aflopend)."""
    return [row for row in (to_row(raw) for raw in rows) if row is not None]


# --- antwoord --------------------------------------------------------------------------

def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _response(
    state: str,
    *,
    message: str | None = None,
    fetched_at: datetime | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(rows or [])
    limit = settings.ahrefs_quick_wins_limit
    stamp = _aware(fetched_at)
    return {
        "state": state,
        "message": message,
        "fetched_at": stamp.isoformat() if stamp else None,
        "limit": limit,
        "capped": len(rows) >= limit,
        "rows": rows,
    }


def _stale_message(error: str) -> str:
    return f"Vernieuwen uit Ahrefs is mislukt; dit is de eerder opgehaalde stand. {error}"


def _stored(record: CustomerQuickWins) -> dict[str, Any]:
    message = _stale_message(record.last_error) if record.last_error else None
    return _response("ok", message=message, fetched_at=record.fetched_at, rows=record.rows)


# --- ophalen en bewaren ----------------------------------------------------------------

def _target(customer: CustomerWebsite) -> str:
    return host_of(customer.base_url or "")


def _country() -> str:
    return (settings.ahrefs_country or "").strip().lower()


def _matches(record: CustomerQuickWins | None, target: str, country: str) -> bool:
    return record is not None and record.target == target and record.country == country


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch(db: Session, customer: CustomerWebsite, target: str, country: str) -> dict[str, Any]:
    """Ophalen uit Ahrefs en bewaren. Bij een fout blijft een eerdere stand van hetzelfde domein staan."""
    record = db.get(CustomerQuickWins, customer.id)
    now = _now()
    try:
        result = ahrefs.organic_keywords(
            target,
            country=country or None,
            position_min=POSITION_MIN,
            position_max=POSITION_MAX,
            limit=settings.ahrefs_quick_wins_limit,
            compare_days=COMPARE_DAYS,
        )
    except AhrefsServiceError as exc:
        error = str(exc)
        if _matches(record, target, country) and record.fetched_at is not None:
            record.last_error = error
            record.updated_at = now
            return _response(
                "ok", message=_stale_message(error), fetched_at=record.fetched_at, rows=record.rows
            )
        # Geen bruikbare eerdere stand: de fout vastleggen zonder `fetched_at`, zodat een volgend
        # bezoek het opnieuw probeert (een mislukte aanroep kost geen units).
        if record is None:
            record = CustomerQuickWins(customer_website_id=customer.id, created_at=now)
            db.add(record)
        record.target, record.country = target, country
        record.rows, record.units, record.fetched_at = [], 0, None
        record.last_error = error
        record.updated_at = now
        return _response("error", message=f"Quick wins niet opgehaald uit Ahrefs: {error}")

    rows = convert(result.rows)
    if record is None:
        record = CustomerQuickWins(customer_website_id=customer.id, created_at=now)
        db.add(record)
    record.target, record.country = target, country
    record.rows = rows
    record.units = result.units
    record.fetched_at = now
    record.last_error = None
    record.updated_at = now
    return _response("ok", fetched_at=now, rows=rows)


def _precheck(customer: CustomerWebsite) -> dict[str, Any] | None:
    if not ahrefs.is_configured():
        return _response("not_configured", message=MESSAGES["not_configured"])
    if not _target(customer):
        return _response("error", message=MESSAGES["no_url"])
    return None


def load(db: Session, customer: CustomerWebsite, *, now: datetime | None = None) -> dict[str, Any]:
    """Bewaarde stand; eerst opnieuw ophalen als die ontbreekt, verlopen is of bij een ander domein hoort.

    Bij `AHREFS_QUICK_WINS_TTL_DAYS = 0` wordt nooit automatisch opgehaald (alleen via `refresh`).
    """
    blocked = _precheck(customer)
    if blocked is not None:
        return blocked
    target, country = _target(customer), _country()
    record = db.get(CustomerQuickWins, customer.id)
    fresh = _matches(record, target, country) and record.fetched_at is not None
    ttl_days = settings.ahrefs_quick_wins_ttl_days

    if ttl_days <= 0:
        return _stored(record) if fresh else _response("ok", message=MESSAGES["not_fetched"])
    if fresh and (now or _now()) - _aware(record.fetched_at) < timedelta(days=ttl_days):
        return _stored(record)
    return _fetch(db, customer, target, country)


def refresh(db: Session, customer: CustomerWebsite) -> dict[str, Any]:
    """Altijd opnieuw ophalen uit Ahrefs en bewaren."""
    blocked = _precheck(customer)
    if blocked is not None:
        return blocked
    return _fetch(db, customer, _target(customer), _country())


# --- samenvoegen met ProRankTracker ----------------------------------------------------

def _in_range(rank: int | None) -> bool:
    return rank is not None and POSITION_MIN <= rank <= POSITION_MAX


def _matched_url(value: Any) -> str | None:
    text = _text(value)
    return None if text is None or text == "None" else text


def best_prt(prt_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per zoekwoord de PRT-rij met de beste (laagste) positie; zonder positie telt als slechtst."""
    best: dict[str, tuple[int | None, dict[str, Any]]] = {}
    for raw in prt_rows:
        key = keyword_key(raw.get("name"))
        if not key:
            continue
        rank = position(raw.get("rank"))
        current = best.get(key)
        if current is None or (rank is not None and (current[0] is None or rank < current[0])):
            best[key] = (rank, raw)
    return {key: raw for key, (_, raw) in best.items()}


def convert_prt(raw: dict[str, Any]) -> dict[str, Any]:
    """Eén PRT-rij in de vorm van een quick win (zonder `kans` en `source`)."""
    rank = position(raw.get("rank"))
    month = position(raw.get("monthagorank"))
    volume = _int(raw.get("localmonthlysearches"))
    return {
        "keyword": _text(raw.get("name")),
        "position": rank,
        "delta": month - rank if month is not None and rank is not None else None,
        "volume": volume if volume is not None and volume >= 0 else None,
        "kd": None,
        "url": _matched_url(raw.get("matchedurl")),
    }


def _sort_key(row: dict[str, Any]) -> tuple:
    volume = row["volume"]
    return (volume is None, -(volume or 0), row["position"], keyword_key(row["keyword"]))


def merge(prt_rows: list[dict[str, Any]], ahrefs_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PRT-rijen (organisch, ruw) en bewaarde Ahrefs-rijen samenvoegen tot quick wins.

    Elk zoekwoord één keer. PRT is leidend voor positie, delta en url (dagelijks gemeten);
    volgt PRT een zoekwoord buiten 4–20, dan vervalt ook de Ahrefs-rij. Het volume komt uit
    PRT als die er is, anders uit Ahrefs; de KD alleen uit Ahrefs. `kans` wordt opnieuw
    berekend. Gesorteerd op volume aflopend (zonder volume achteraan), positie, zoekwoord.
    """
    prt_best = best_prt(prt_rows)
    merged: dict[str, dict[str, Any]] = {}

    for row in ahrefs_rows:
        key = keyword_key(row.get("keyword"))
        if not key or key in merged:
            continue
        raw = prt_best.get(key)
        if raw is None:
            merged[key] = {**row, "source": "ahrefs"}
            continue
        prt_row = convert_prt(raw)
        if not _in_range(prt_row["position"]):
            continue  # PRT meet buiten 4–20: geen quick win
        merged[key] = {
            **prt_row,
            "volume": prt_row["volume"] if prt_row["volume"] is not None else row.get("volume"),
            "kd": row.get("kd"),
            "source": "both",
        }

    for key, raw in prt_best.items():
        if key in merged:
            continue
        prt_row = convert_prt(raw)
        if _in_range(prt_row["position"]) and prt_row["keyword"]:
            merged[key] = {**prt_row, "source": "prt"}

    rows = [{**row, "kans": kans(row["position"], row["kd"], row["volume"])} for row in merged.values()]
    return sorted(rows, key=_sort_key)


PRT_ERROR_MESSAGE = "De zoekwoorden uit ProRankTracker konden niet worden opgehaald."


def combine(ahrefs_result: dict[str, Any], prt_state: str, prt_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Het Ahrefs-antwoord (`load`/`refresh`) en de PRT-uitkomst (`organic_rows`) samenvoegen.

    `ok` zodra minstens één bron bruikbaar is (PRT "niet gevolgd" telt als bruikbaar zonder
    rijen); `not_configured` als geen van beide is gekoppeld; anders `error`. De Ahrefs-melding
    blijft staan; een PRT-fout komt erachter. `fetched_at`, `limit` en `capped` blijven die van
    Ahrefs.
    """
    ahrefs_state = ahrefs_result["state"]
    ahrefs_ok = ahrefs_state == "ok"
    prt_ok = prt_state in ("ok", "not_tracked")

    if ahrefs_ok or prt_ok:
        state = "ok"
    elif ahrefs_state == "not_configured" and prt_state == "not_configured":
        state = "not_configured"
    else:
        state = "error"

    prt_message = None
    if prt_state == "error":
        prt_message = PRT_ERROR_MESSAGE
    elif state == "not_configured":
        prt_message = STATE_MESSAGES["not_configured"]
    message = " ".join(m for m in (ahrefs_result.get("message"), prt_message) if m) or None

    return {
        **ahrefs_result,
        "state": state,
        "message": message,
        "rows": merge(prt_rows if prt_ok else [], ahrefs_result.get("rows") or []),
    }


def load_merged(db: Session, customer: CustomerWebsite, *, now: datetime | None = None) -> dict[str, Any]:
    """`load` (Ahrefs, bewaard) samengevoegd met de live opgehaalde PRT-zoekwoorden."""
    ahrefs_result = load(db, customer, now=now)
    prt_state, prt_rows, _ = organic_rows(customer.base_url or "")
    return combine(ahrefs_result, prt_state, prt_rows)


def refresh_merged(db: Session, customer: CustomerWebsite) -> dict[str, Any]:
    """`refresh` (Ahrefs, altijd opnieuw) samengevoegd met de live opgehaalde PRT-zoekwoorden."""
    ahrefs_result = refresh(db, customer)
    prt_state, prt_rows, _ = organic_rows(customer.base_url or "")
    return combine(ahrefs_result, prt_state, prt_rows)
