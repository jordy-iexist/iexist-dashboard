"""Vastgelopen livegang-scans herstellen.

Een scan die stopt door de harde tijdslimiet of een herstart van de worker,
blijft op een actieve status staan. Zolang dat zo is weigeren alle
start-endpoints een nieuwe scan voor die klant (409). `recover_stale_scan`
zet zo'n scan op 'failed', zodat hij opnieuw kan worden gestart.

Een fase-3 AI-analyse ('analyzing' op een fase-3 scan) valt hier buiten: die
herstelt `content_rebuild.recover_stale_analysis` naar 'completed', omdat de
scan zelf dan al klaar is.

De workers werken `updated_at` bij na elke batch of stap (hun `_update`); waar
een stap lang kan duren zonder batches, geeft `heartbeat` een levensteken.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import LaunchScan
from app.features.launch_checklist.schemas import ACTIVE_STATUSES

# Zo lang mag een lopende scan niets van zich laten horen (`updated_at`). De workers
# werken `updated_at` bij na elke batch of stap, en via `heartbeat` tijdens lange stappen.
STALE_SCAN_AFTER = timedelta(minutes=30)
# Zo lang mag een scan op 'pending' wachten (`created_at`) voordat de taak als verloren
# geldt. Alleen voor 'pending': bij een lopende scan telt `created_at` ook de wachttijd
# in de rij mee, terwijl de harde tijdslimiet (3600 s) pas begint als de worker start.
SCAN_MAX_AGE = timedelta(minutes=65)
# Hooguit zo vaak schrijft `heartbeat` naar de database.
HEARTBEAT_INTERVAL_SECONDS = 60.0

INTERRUPTED_SCAN_MESSAGE = (
    "De scan is onderbroken (bijvoorbeeld door een herstart van de server) en kan opnieuw worden gestart."
)


def as_utc(value: datetime | None) -> datetime | None:
    """Tijdstip met tijdzone; een naïeve waarde (bijv. uit SQLite) geldt als UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_older_than(value: datetime | None, limit: timedelta, *, now: datetime | None = None) -> bool:
    """Of `value` langer dan `limit` geleden is; False als het tijdstip ontbreekt."""
    value = as_utc(value)
    if value is None:
        return False
    return (now or datetime.now(timezone.utc)) - value >= limit


def recover_stale_scan(db: Session, scan: LaunchScan, *, now: datetime | None = None) -> bool:
    """Zet een actieve scan die niet meer loopt op 'failed'. True als dat gebeurd is.

    - 'pending': vastgelopen als `created_at` ouder is dan SCAN_MAX_AGE. De scan
      kan in de wachtrij staan achter andere taken, en de worker werkt
      `updated_at` pas bij als hij begint.
    - elke andere actieve status: vastgelopen als `updated_at` ouder is dan
      STALE_SCAN_AFTER. Geen leeftijdsregel: een lange scan die op tijd een
      levensteken geeft, loopt nog.
    """
    status = str(scan.status or "").lower()
    if status not in ACTIVE_STATUSES:
        return False
    if scan.phase == 3 and status == "analyzing":
        return False  # recover_stale_analysis
    now = now or datetime.now(timezone.utc)
    if status == "pending":
        stale = is_older_than(scan.created_at, SCAN_MAX_AGE, now=now)
    else:
        stale = is_older_than(scan.updated_at, STALE_SCAN_AFTER, now=now)
    if not stale:
        return False
    scan.status = "failed"
    scan.error_message = INTERRUPTED_SCAN_MESSAGE
    scan.updated_at = now
    db.commit()
    return True


def heartbeat(touch: Callable[[], Any], interval: float = HEARTBEAT_INTERVAL_SECONDS) -> Callable[[], None]:
    """Functie die `touch` hooguit eens per `interval` seconden aanroept.

    Voor stappen die lang kunnen duren zonder voortgang naar de database te
    schrijven. Thread-safe: de URL-inspectie roept hem vanuit meerdere threads aan.
    """
    lock = threading.Lock()
    last = [time.monotonic()]

    def beat() -> None:
        with lock:
            if time.monotonic() - last[0] < interval:
                return
            last[0] = time.monotonic()
        touch()

    return beat
