"""Koppel bestaande blogs met terugwerkende kracht aan de juiste klant.

De klant-koppeling op blogs (`Blog.customer_website_id`) is pas later toegevoegd; blogs die
daarvoor gegenereerd zijn — of waarvan de klant toen nog niet bestond — staan op `NULL`. Dit
script haalt die achterstand in. Het overschrijft nooit een blog die al een klant heeft.

`Blog` bevat zelf geen klantnaam; die zit in `CsvRow.data`, bereikbaar via
`Blog.job_id -> Job.row_id -> CsvRow.id`. Er wordt in twee stappen gematcht, eerste treffer
wint:

  1. Klantnaam (veld 'klant', met terugval op 'klantnaam'/'bedrijf'/'customer') tegen de
     naam van een klant — exact, hoofdletterongevoelig.
  2. Anker-URL's (velden die op '_url' eindigen) tegen het domein van een klant.

Zowel actieve als gearchiveerde klanten tellen mee, zodat oud-klanten hun archief houden.
Naamgelijkheid of tegenstrijdige anker-domeinen worden overgeslagen in plaats van geraden.

──────────────────────────────────────────────────────────────────────────────
LOKAAL (vanuit de backend/ map, met geactiveerde venv)
──────────────────────────────────────────────────────────────────────────────
Let op: dit raakt je LOKALE database, niet die van de server.

  # Eerst een droogloop om te zien wat er zou gebeuren:
  python scripts/backfill_blog_customers.py --dry-run

  # Daadwerkelijk koppelen:
  python scripts/backfill_blog_customers.py

──────────────────────────────────────────────────────────────────────────────
OP DE SERVER (Docker, vanuit de projectmap, bv. ~/iexist-dashboard)
──────────────────────────────────────────────────────────────────────────────
Maak eerst een database-dump (zie DEPLOY.md, "Backups") — dit raakt in één keer alle
historische blogs. Draai het script daarna in de draaiende `api`-container.

  docker compose -f docker-compose.prod.yml exec api \
    python scripts/backfill_blog_customers.py --dry-run

  # Zonder interactieve bevestiging (bv. in een script):
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/backfill_blog_customers.py --yes
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Zorg dat het 'app'-package importeerbaar is, ongeacht vanuit welke map het
# script wordt gestart (bv. `python scripts/backfill_blog_customers.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import Blog, CsvRow, CustomerWebsite, Job  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.features.seo_tracker.services import to_root_domain  # noqa: E402

NAME_FIELD_CANDIDATES = ["klant", "klantnaam", "bedrijf", "customer"]


class Match:
    """Resultaat van het matchen van één blog."""

    def __init__(self, blog_id: str, *, customer_id: str | None = None, method: str | None = None, skip_reason: str | None = None):
        self.blog_id = blog_id
        self.customer_id = customer_id
        self.method = method
        self.skip_reason = skip_reason


def _build_indexes(db: Any) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    """Bouw naam- en domein-index over ALLE klanten (ook gearchiveerde)."""
    name_index: dict[str, list[str]] = defaultdict(list)
    domain_index: dict[str, list[str]] = defaultdict(list)
    names_by_id: dict[str, str] = {}

    for customer_id, name, domain in db.query(CustomerWebsite.id, CustomerWebsite.name, CustomerWebsite.domain).all():
        names_by_id[customer_id] = str(name or "").strip()
        normalized_name = str(name or "").strip().lower()
        if normalized_name:
            name_index[normalized_name].append(customer_id)
        normalized_domain = str(domain or "").strip().lower()
        if normalized_domain:
            domain_index[normalized_domain].append(customer_id)

    return dict(name_index), dict(domain_index), names_by_id


def _extract_name(row_data: dict[str, Any]) -> str:
    for field in NAME_FIELD_CANDIDATES:
        value = str(row_data.get(field, "") or "").strip()
        if value:
            return value
    return ""


def _extract_anchor_domains(row_data: dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    for key, value in row_data.items():
        if not key.endswith("_url"):
            continue
        raw = str(value or "").strip()
        if not raw:
            continue
        try:
            domains.add(to_root_domain(raw))
        except ValueError:
            continue
    return domains


def _match_blog(row_data: Any, name_index: dict[str, list[str]], domain_index: dict[str, list[str]]) -> Match | tuple[str | None, str | None]:
    """Retourneert (customer_id, method) bij een match, of (None, skip_reason) anders."""
    if not isinstance(row_data, dict):
        return None, "geen csv-rij"

    name = _extract_name(row_data)
    if name:
        candidates = name_index.get(name.lower(), [])
        if len(candidates) == 1:
            return candidates[0], "naam"
        if len(candidates) > 1:
            return None, f"meerdere klanten met naam '{name}'"

    anchor_domains = _extract_anchor_domains(row_data)
    matched_customers = {
        customer_id
        for domain in anchor_domains
        for customer_id in domain_index.get(domain, [])
    }
    if len(matched_customers) == 1:
        return next(iter(matched_customers)), "anker-url"
    if len(matched_customers) > 1:
        return None, "tegenstrijdige anker-domeinen"

    if name:
        return None, f"klantnaam '{name}' onbekend"
    return None, "geen bruikbaar signaal"


def main() -> int:
    parser = argparse.ArgumentParser(description="Koppel bestaande blogs met terugwerkende kracht aan de juiste klant.")
    parser.add_argument("--dry-run", action="store_true", help="Toon wat er zou gebeuren zonder iets weg te schrijven.")
    parser.add_argument("--yes", action="store_true", help="Sla de interactieve bevestiging over.")
    args = parser.parse_args()

    with SessionLocal() as db:
        name_index, domain_index, names_by_id = _build_indexes(db)

        rows = (
            db.query(Blog.id, CsvRow.data)
            .join(Job, Job.id == Blog.job_id)
            .outerjoin(CsvRow, CsvRow.id == Job.row_id)
            .filter(Blog.customer_website_id.is_(None))
            .all()
        )

        if not rows:
            print("Geen ongekoppelde blogs gevonden.")
            return 0

        print(f"{len(rows)} ongekoppelde blog(s) gevonden.\n")

        matches = [_match_blog(row_data, name_index, domain_index) for _, row_data in rows]

        blog_ids_by_customer: dict[str, list[str]] = defaultdict(list)
        methods_by_customer: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        skip_reason_counts: dict[str, int] = defaultdict(int)

        for (blog_id, _), (customer_id, method_or_reason) in zip(rows, matches):
            if customer_id:
                blog_ids_by_customer[customer_id].append(blog_id)
                methods_by_customer[customer_id][method_or_reason] += 1
            else:
                skip_reason_counts[method_or_reason] += 1

        total_to_link = sum(len(ids) for ids in blog_ids_by_customer.values())

        print(f"Te koppelen: {total_to_link}")
        for customer_id, blog_ids in sorted(blog_ids_by_customer.items(), key=lambda item: names_by_id.get(item[0], "")):
            methods = methods_by_customer[customer_id]
            breakdown = ", ".join(f"{count}x {method}" for method, count in sorted(methods.items()))
            print(f"  + {names_by_id.get(customer_id, customer_id)}: {len(blog_ids)} blog(s) ({breakdown})")

        print(f"\nOvergeslagen: {sum(skip_reason_counts.values())}")
        for reason, count in sorted(skip_reason_counts.items(), key=lambda item: item[0]):
            print(f"  - {reason}: {count}")

        if not total_to_link:
            print("\nNiets om te koppelen.")
            return 0

        if args.dry_run:
            print(f"\nDry-run: er is niets weggeschreven ({total_to_link} zouden zijn gekoppeld).")
            return 0

        if not args.yes:
            confirm = input(f"\n{total_to_link} blog(s) koppelen aan een klant? Typ 'ja' om te bevestigen: ").strip().lower()
            if confirm != "ja":
                print("Geannuleerd.", file=sys.stderr)
                return 1

        for customer_id, blog_ids in blog_ids_by_customer.items():
            db.query(Blog).filter(
                Blog.id.in_(blog_ids), Blog.customer_website_id.is_(None)
            ).update({"customer_website_id": customer_id}, synchronize_session=False)
        db.commit()

        print(f"\n{total_to_link} blog(s) gekoppeld.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
