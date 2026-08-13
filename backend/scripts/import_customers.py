"""Importeer klanten (naam + url) in bulk vanuit een CSV-bestand.

Herbruikt dezelfde CSV-parser als de blog-upload en dezelfde URL-normalisatie
als het aanmaken van een klant via het dashboard, zodat een geïmporteerde
klant er niet anders uitziet dan een handmatig aangemaakte. Klanten met een
domein dat al bestaat worden overgeslagen (nooit overschreven), dus de import
is veilig herhaalbaar met hetzelfde bestand.

De CSV heeft minimaal twee kolommen nodig: een naam-kolom en een url-kolom.
Kolomnamen worden automatisch herkend (naam/name/klant/klantnaam/bedrijf/
customer en url/website/site/base_url/domein/domain/link, hoofdletter-
ongevoelig); gebruik --name-column / --url-column als dat niet lukt.

Voorbeeld-CSV:

    naam,url
    Klant A,https://klant-a.nl
    Klant B,klant-b.nl

──────────────────────────────────────────────────────────────────────────────
LOKAAL (vanuit de backend/ map, met geactiveerde venv)
──────────────────────────────────────────────────────────────────────────────
Let op: dit raakt je LOKALE database, niet die van de server.

  # Eerst een droogloop om te zien wat er zou gebeuren:
  python scripts/import_customers.py klanten.csv --email jij@voorbeeld.nl --dry-run

  # Daadwerkelijk importeren:
  python scripts/import_customers.py klanten.csv --email jij@voorbeeld.nl

──────────────────────────────────────────────────────────────────────────────
OP DE SERVER (Docker, vanuit de projectmap, bv. ~/iexist-dashboard)
──────────────────────────────────────────────────────────────────────────────
Kopieer het CSV-bestand eerst de container in, draai daarna het script in de
draaiende `api`-container; die heeft de juiste DATABASE_URL en dependencies.

  docker compose -f docker-compose.prod.yml cp klanten.csv api:/tmp/klanten.csv
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/import_customers.py /tmp/klanten.csv --email jij@voorbeeld.nl --dry-run

  # Zonder interactieve bevestiging (bv. in een script):
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/import_customers.py /tmp/klanten.csv --email jij@voorbeeld.nl --yes
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

# Zorg dat het 'app'-package importeerbaar is, ongeacht vanuit welke map het
# script wordt gestart (bv. `python scripts/import_customers.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.auth import get_user_by_email, normalize_email  # noqa: E402
from app.core.dependencies import utc_now_iso  # noqa: E402
from app.db.models import CustomerWebsite  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.features.blogs.services.generation.csv import parse_csv  # noqa: E402
from app.features.seo_tracker.services import normalize_website_url  # noqa: E402

NAME_COLUMN_CANDIDATES = ["naam", "name", "klant", "klantnaam", "bedrijf", "customer"]
URL_COLUMN_CANDIDATES = ["url", "website", "site", "base_url", "domein", "domain", "link"]


class ImportRow:
    """Resultaat van het verwerken van één CSV-rij."""

    def __init__(self, label: str, *, website: CustomerWebsite | None = None, skip_reason: str | None = None):
        self.label = label
        self.website = website
        self.skip_reason = skip_reason


def _detect_column(headers: list[str], candidates: list[str], override: str | None, kind: str) -> str:
    if override:
        if override not in headers:
            raise ValueError(
                f"Kolom '{override}' voor {kind} niet gevonden. Beschikbare kolommen: {', '.join(headers)}."
            )
        return override

    lookup = {header.strip().lower(): header for header in headers}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]

    raise ValueError(
        f"Geen kolom voor {kind} gevonden (geprobeerd: {', '.join(candidates)}). "
        f"Beschikbare kolommen: {', '.join(headers)}. Gebruik --{kind}-column om te overschrijven."
    )


def _process_rows(
    rows: list[dict[str, Any]],
    name_column: str,
    url_column: str,
    seen_domains: set[str],
    created_by: str,
) -> list[ImportRow]:
    results: list[ImportRow] = []
    now = utc_now_iso()

    for row in rows:
        name = str(row.get(name_column, "") or "").strip()
        raw_url = str(row.get(url_column, "") or "").strip()
        label = f"'{name or '(geen naam)'}' ({raw_url or 'geen url'})"

        if not name:
            results.append(ImportRow(label, skip_reason="naam ontbreekt"))
            continue
        if not raw_url:
            results.append(ImportRow(label, skip_reason="url ontbreekt"))
            continue

        try:
            normalized_base_url, root_domain = normalize_website_url(raw_url)
        except ValueError as exc:
            results.append(ImportRow(label, skip_reason=str(exc)))
            continue

        if root_domain in seen_domains:
            results.append(ImportRow(label, skip_reason="domein bestaat al"))
            continue

        website = CustomerWebsite(
            id=str(uuid.uuid4()),
            name=name,
            base_url=normalized_base_url,
            domain=root_domain,
            is_active=True,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        seen_domains.add(root_domain)
        results.append(ImportRow(label, website=website))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Importeer klanten (naam + url) uit een CSV-bestand.")
    parser.add_argument("csv_path", help="Pad naar het CSV-bestand.")
    parser.add_argument("--email", required=True, help="E-mailadres van het account dat als eigenaar geldt.")
    parser.add_argument("--name-column", default=None, help="Kolomnaam voor de klantnaam (auto-detect als niet opgegeven).")
    parser.add_argument("--url-column", default=None, help="Kolomnaam voor de website-url (auto-detect als niet opgegeven).")
    parser.add_argument("--dry-run", action="store_true", help="Toon wat er zou gebeuren zonder iets weg te schrijven.")
    parser.add_argument("--yes", action="store_true", help="Sla de interactieve bevestiging over.")
    args = parser.parse_args()

    email = normalize_email(args.email)
    if not email:
        print("E-mailadres is verplicht.", file=sys.stderr)
        return 1

    user = get_user_by_email(email)
    if not user:
        print(f"Geen account gevonden met '{email}'.", file=sys.stderr)
        return 1

    csv_path = Path(args.csv_path)
    if not csv_path.is_file():
        print(f"Bestand niet gevonden: {csv_path}", file=sys.stderr)
        return 1

    try:
        headers, rows = parse_csv(csv_path.read_bytes())
    except ValueError as exc:
        print(f"Kon CSV niet lezen: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("CSV bevat geen (bruikbare) rijen.", file=sys.stderr)
        return 1

    try:
        name_column = _detect_column(headers, NAME_COLUMN_CANDIDATES, args.name_column, "naam")
        url_column = _detect_column(headers, URL_COLUMN_CANDIDATES, args.url_column, "url")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Kolommen: naam='{name_column}', url='{url_column}'. {len(rows)} rij(en) gevonden in {csv_path}.")

    with SessionLocal() as db:
        seen_domains = {domain for (domain,) in db.query(CustomerWebsite.domain).all()}
        results = _process_rows(rows, name_column, url_column, seen_domains, str(user["id"]))

        to_create = [result for result in results if result.website is not None]
        skipped = [result for result in results if result.skip_reason is not None]

        print(f"\nAan te maken: {len(to_create)}")
        for result in to_create:
            print(f"  + {result.label}")

        print(f"\nOvergeslagen: {len(skipped)}")
        for result in skipped:
            print(f"  - {result.label} — {result.skip_reason}")

        if not to_create:
            print("\nNiets om te importeren.")
            return 0

        if args.dry_run:
            print(f"\nDry-run: er is niets weggeschreven ({len(to_create)} zouden zijn aangemaakt).")
            return 0

        if not args.yes:
            confirm = input(f"\n{len(to_create)} klant(en) aanmaken? Typ 'ja' om te bevestigen: ").strip().lower()
            if confirm != "ja":
                print("Geannuleerd.", file=sys.stderr)
                return 1

        for result in to_create:
            db.add(result.website)
        db.commit()

        print(f"\n{len(to_create)} klant(en) aangemaakt.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
