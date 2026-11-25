"""Contract van het scherm Zoekwoorden › Content gap (per klant).

Een content gap: zoekwoorden waarop minstens `MIN_COMPETITORS` van de vijf concurrenten uit de
concurrentenscan (`Snapshot.competitors` met `in_top5`) in de Google top 10 staan en de klant
niet. Geen AI in deze stap.

Eén bestand voor de ophaler (`services/gap_collect.py`), de rekenregels
(`services/gap_compute.py`), de worker (`worker/gap.py`) en de router (`gap_router.py`):
1. Literal-types en constanten.
2. De tussenvormen (`GapCandidate`, `PositionCheck`).
3. De vorm van de JSON-kolom `data` van `customer_keyword_gaps` (`GapSnapshot`). Schrijven:
   `GapSnapshot(...).model_dump(mode="json")`; lezen: `GapSnapshot.model_validate(waarde)`.
4. Het antwoord van `/api/keywords/customers/{cid}/content-gap` (`ContentGapOverview`).

Conventies zoals in `features/keywords/schemas.py`: een domein is een kale host zonder `www.`,
zoekwoorden worden vergeleken met `rankings.keyword_key` (de getoonde tekst is de eerste
schrijfwijze die binnenkwam), tijdstippen zijn UTC en Ahrefs-verbruik is in units.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.features.competitor_analysis.services.estimate import AHREFS_UNITS_PER_KEYWORD

# --- Statussen en constanten -----------------------------------------------------------------

# idle = nog nooit gestart. pending (router) → collecting (lijsten, kandidaten, posities) →
# enriching (volume, KD, intentie) → completed of failed. Bij failed blijft `data` staan.
GapStatus = Literal["idle", "pending", "collecting", "enriching", "completed", "failed"]
ACTIVE_GAP_STATUSES: frozenset[str] = frozenset({"pending", "collecting", "enriching"})

# Waarom starten niet kan (POST start geeft dan 400). Volgorde van controleren: Ahrefs niet
# ingesteld → geen voltooide concurrentenscan voor het huidige klantdomein → minder dan
# `MIN_COMPETITORS` concurrenten met `in_top5`.
GapBlockedReason = Literal["no_scan", "too_few_competitors", "ahrefs_not_configured"]

# Een zoekwoord is een gap als minstens zoveel concurrenten in de top 10 staan.
MIN_COMPETITORS = 2
TOP10 = 10

# Units per uitgewerkt zoekwoord: volume, KD en intentie 31 (gemeten, zie
# competitor_analysis/services/estimate.py) plus de posities bij vijf concurrenten en de klant,
# geschat op 8 (2 units per teruggegeven rij, circa vier rijen per zoekwoord; op het gratis
# testdomein ahrefs.com niet per rij te meten, zie de Ahrefs-client).
UNITS_PER_GAP_KEYWORD_FACTS = AHREFS_UNITS_PER_KEYWORD
UNITS_PER_GAP_KEYWORD_POSITIONS = 8
UNITS_PER_GAP_KEYWORD = UNITS_PER_GAP_KEYWORD_FACTS + UNITS_PER_GAP_KEYWORD_POSITIONS  # 39

# --- tussenvormen ----------------------------------------------------------------------------


class GapCandidate(BaseModel):
    """Gap-kandidaat na stap 2: in minstens twee lijsten van de vijf, niet in die van de klant.

    `domains` zijn de concurrenten in wier top 10-lijst het zoekwoord staat (in kolomvolgorde);
    `first_index` is de vroegste plek in die lijsten (de lijsten staan op verkeer aflopend).
    """

    keyword: str
    key: str
    domains: list[str] = Field(default_factory=list)
    first_index: int = 0


class PositionCheck(BaseModel):
    """Navraag van posities bij één domein (stap 4).

    `checked`: sleutels die echt zijn nagevraagd (een overgeslagen deel ontbreekt).
    `positions`: beste positie per sleutel; wat niet terugkwam rankt niet (binnen de grens).
    """

    checked: set[str] = Field(default_factory=set)
    positions: dict[str, int] = Field(default_factory=dict)


# --- data: het resultaat ---------------------------------------------------------------------


class GapKeyword(BaseModel):
    keyword: str
    volume: int | None = None
    kd: int | None = None
    # Ahrefs-namen: commercial, informational, local, transactional, navigational, branded.
    intents: list[str] = Field(default_factory=list)
    competitors_count: int = 0  # hoeveel van de concurrenten in de top 10 staan
    positions: dict[str, int | None] = Field(default_factory=dict)  # één sleutel per concurrent
    own_position: int | None = None  # positie van de klant buiten de top 10, anders None


class GapSnapshot(BaseModel):
    customer_domain: str
    competitors: list[str] = Field(default_factory=list)  # kolomvolgorde
    found: int = 0  # alle gap-kandidaten, ook de niet-uitgewerkte
    keywords: list[GapKeyword] = Field(default_factory=list)  # volume aflopend, onbekend achteraan
    warnings: list[str] = Field(default_factory=list)


# --- API: /api/keywords/customers/{cid}/content-gap ------------------------------------------


class ContentGapOverview(BaseModel):
    """Antwoord van GET en POST start. Zonder resultaat zijn `keywords` leeg en `found` 0."""

    status: GapStatus
    error: str | None = None  # foutmelding van de laatste mislukte run
    blocked: GapBlockedReason | None = None
    has_result: bool = False  # er is een opgeslagen resultaat (ook tijdens of na een mislukte run)
    customer_domain: str = ""
    # Van het resultaat; zonder resultaat de huidige vijf uit de concurrentenscan.
    competitors: list[str] = Field(default_factory=list)
    found: int = 0
    keywords: list[GapKeyword] = Field(default_factory=list)
    units: int = 0  # Ahrefs-units van de laatste run
    max_units: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stale: bool = False  # de concurrentenscan is na deze content gap vernieuwd
    warnings: list[str] = Field(default_factory=list)


# --- Afgesproken functies per module ---------------------------------------------------------
#
# services/gap_collect.py (ophalen; elke Ahrefs-aanroep loopt via `collect.UnitBudget`)
#   def collect_lists(raw: Raw, *, customer_domain: str, competitors: list[str], country: str,
#                     budget: UnitBudget) -> dict[str, list[str]]
#       Stap 1: top 10-lijsten van klant + concurrenten uit `raw.top10`, ontbrekende ophalen.
#   def collect_positions(domain: str, keywords: list[str], *, country: str,
#                         max_position: int | None, budget: UnitBudget) -> PositionCheck
#       Stap 4 voor één domein, in delen van `collect.CHECK_CHUNK`.
#   def collect_facts(keywords: list[str], *, country: str,
#                     budget: UnitBudget) -> dict[str, KeywordFacts]
#       Stap 5: volume, KD en intentie; past het niet, dan zoveel als het budget toelaat.
#   Een Ahrefs-fout met een code uit `FATAL_CODES` wordt doorgegooid (run `failed`); andere
#   fouten slaan alleen die stap over en komen in `budget.skipped`.
#
# services/gap_compute.py (puur, geen I/O)
#   def max_keywords(units: int) -> int
#   def candidates(lists: dict[str, list[str]], *, customer_domain: str,
#                  competitors: list[str]) -> list[GapCandidate]
#   def build_snapshot(items: list[GapCandidate], *, limit: int, customer_domain: str,
#                      competitors: list[str], checks: dict[str, PositionCheck],
#                      facts: dict[str, KeywordFacts], warnings: list[str]) -> GapSnapshot
