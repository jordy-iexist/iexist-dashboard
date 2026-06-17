"""Verwijder een gebruikersaccount handmatig.

Verwijdert de gebruiker én de bijbehorende per-user rijen (refresh-tokens en de
drie settings-tabellen die op user_id staan), zodat er geen weesrecords
achterblijven. Gegenereerde content (CSV-uploads, blogs, websites, audits) is in
dit schema niet aan een user_id gekoppeld en blijft dus staan.

Ter bevestiging moet je het e-mailadres nog een keer typen, tenzij je --yes
meegeeft.

──────────────────────────────────────────────────────────────────────────────
LOKAAL (vanuit de backend/ map, met geactiveerde venv)
──────────────────────────────────────────────────────────────────────────────
Let op: dit raakt je LOKALE database, niet die van de server.

  python scripts/delete_user.py --email iemand@voorbeeld.nl

──────────────────────────────────────────────────────────────────────────────
OP DE SERVER (Docker, vanuit de projectmap, bv. ~/iexist-dashboard)
──────────────────────────────────────────────────────────────────────────────
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/delete_user.py --email iemand@voorbeeld.nl

  # Zonder interactieve bevestiging (bv. in een script):
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/delete_user.py --email iemand@voorbeeld.nl --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Zorg dat het 'app'-package importeerbaar is, ongeacht vanuit welke map het
# script wordt gestart (bv. `python scripts/delete_user.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.auth import get_user_by_email, normalize_email  # noqa: E402
from app.db.models import (  # noqa: E402
    AuthRefreshToken,
    BlogGenerationSettings,
    LandingPageGenerationSettings,
    User,
    UserAISettings,
)
from app.db.session import SessionLocal  # noqa: E402

# Tabellen met een losse user_id-kolom (geen FK), die per gebruiker opgeruimd
# moeten worden bij het verwijderen van een account.
USER_OWNED_MODELS = (
    AuthRefreshToken,
    BlogGenerationSettings,
    LandingPageGenerationSettings,
    UserAISettings,
)


def _delete_user(user_id: str) -> dict[str, int]:
    """Verwijder de gebruiker en bijbehorende rijen. Geeft aantallen per tabel terug."""
    deleted: dict[str, int] = {}
    with SessionLocal() as db:
        for model in USER_OWNED_MODELS:
            count = (
                db.query(model)
                .filter(model.user_id == user_id)
                .delete(synchronize_session=False)
            )
            deleted[model.__tablename__] = count
        deleted["users"] = (
            db.query(User)
            .filter(User.id == user_id)
            .delete(synchronize_session=False)
        )
        db.commit()
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Verwijder een gebruikersaccount.")
    parser.add_argument("--email", required=True, help="E-mailadres van het account.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Sla de interactieve bevestiging over.",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    if not email:
        print("E-mailadres is verplicht.", file=sys.stderr)
        return 1

    user = get_user_by_email(email)
    if not user:
        print(f"Geen account gevonden met '{email}'.", file=sys.stderr)
        return 1

    print(f"Gevonden account: {user['email']} (id: {user['id']}).")
    if not args.yes:
        confirm = input(
            f"Typ het e-mailadres ter bevestiging van verwijderen ({email}): "
        ).strip().lower()
        if confirm != email:
            print("Bevestiging komt niet overeen. Geannuleerd.", file=sys.stderr)
            return 1

    deleted = _delete_user(str(user["id"]))
    extra = ", ".join(
        f"{table}: {count}" for table, count in deleted.items() if table != "users"
    )
    print(f"Account verwijderd: {email}. Opgeruimde rijen — {extra}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
