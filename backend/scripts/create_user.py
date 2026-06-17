"""Maak (of werk) een gebruikersaccount handmatig aan.

Publieke registratie is uitgeschakeld; dit script is de enige manier om accounts
aan te maken. Hergebruikt de bestaande auth-helpers zodat wachtwoorden op exact
dezelfde manier worden gehasht als bij de reguliere login.

Het wachtwoord wordt altijd interactief gevraagd (2x ter controle) en verschijnt
dus niet in de shell-history of in de procesargumenten.

──────────────────────────────────────────────────────────────────────────────
LOKAAL (vanuit de backend/ map, met geactiveerde venv)
──────────────────────────────────────────────────────────────────────────────
Let op: dit raakt je LOKALE database, niet die van de server.

  # Nieuw account aanmaken:
  python scripts/create_user.py --email iemand@voorbeeld.nl

  # Wachtwoord van een bestaand account wijzigen:
  python scripts/create_user.py --email iemand@voorbeeld.nl --update-password

──────────────────────────────────────────────────────────────────────────────
OP DE SERVER (Docker, vanuit de projectmap, bv. ~/iexist-dashboard)
──────────────────────────────────────────────────────────────────────────────
Draai het script in de draaiende `api`-container; die heeft de juiste
DATABASE_URL en alle dependencies. `exec` geeft een TTY, dus de wachtwoord-prompt
werkt gewoon.

  # Nieuw account aanmaken:
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/create_user.py --email iemand@voorbeeld.nl

  # Wachtwoord van een bestaand account wijzigen:
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/create_user.py --email iemand@voorbeeld.nl --update-password
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path

# Zorg dat het 'app'-package importeerbaar is, ongeacht vanuit welke map het
# script wordt gestart (bv. `python scripts/create_user.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.auth import (  # noqa: E402
    create_user,
    get_user_by_email,
    hash_password,
    normalize_email,
)
from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

MIN_PASSWORD_LENGTH = 8


def _prompt_password() -> str:
    while True:
        password = getpass("Wachtwoord: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"Wachtwoord moet minimaal {MIN_PASSWORD_LENGTH} tekens lang zijn.",
                file=sys.stderr,
            )
            continue
        confirm = getpass("Wachtwoord (nogmaals): ")
        if password != confirm:
            print("Wachtwoorden komen niet overeen. Probeer opnieuw.", file=sys.stderr)
            continue
        return password


def _update_password(email: str, password: str) -> None:
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:  # defensief; aanroeper controleert dit al
            raise ValueError("Gebruiker niet gevonden.")
        user.password_hash = hash_password(password)
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)


def main() -> int:
    parser = argparse.ArgumentParser(description="Maak handmatig een gebruikersaccount aan.")
    parser.add_argument("--email", required=True, help="E-mailadres van het account.")
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="Werk het wachtwoord bij als het account al bestaat.",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    if not email:
        print("E-mailadres is verplicht.", file=sys.stderr)
        return 1

    existing = get_user_by_email(email)
    if existing and not args.update_password:
        print(
            f"Er bestaat al een account met '{email}'. "
            "Gebruik --update-password om het wachtwoord te wijzigen.",
            file=sys.stderr,
        )
        return 1

    password = _prompt_password()

    if existing:
        _update_password(email, password)
        print(f"Wachtwoord bijgewerkt voor {email} (id: {existing['id']}).")
        return 0

    user = create_user(email, password)
    print(f"Account aangemaakt: {user['email']} (id: {user['id']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
