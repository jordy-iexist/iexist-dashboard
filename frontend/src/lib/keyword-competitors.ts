/**
 * Zoekwoorden › Concurrenten per klant: types, hulpjes en de API-aanroepen.
 * Alles loopt via de proxy onder `/api/keywords`.
 *
 * De types volgen `backend/app/features/keywords/schemas.py` één-op-één (zelfde veldnamen).
 * Een domein is een kale host zonder `www.`; percentages zijn 0–100; tijdstippen ISO met
 * tijdzone; Ahrefs in units, Claude-verbruik in USD (`AiUsage.cost_usd`).
 */

import type { AiUsage } from "@/lib/competitor-analysis"

// --- Statussen en constanten ----------------------------------------------------------------

/** `idle` = nog nooit opgehaald. */
export type OverviewStatus =
  | "idle"
  | "pending"
  | "collecting"
  | "classifying"
  | "summarizing"
  | "completed"
  | "failed"

export const ACTIVE_OVERVIEW_STATUSES: readonly OverviewStatus[] = [
  "pending",
  "collecting",
  "classifying",
  "summarizing",
]

export type CompetitorType = "landelijk" | "regio" | "lokaal"

export const COMPETITOR_TYPE_LABELS: Record<CompetitorType, string> = {
  landelijk: "Landelijk",
  regio: "Regio",
  lokaal: "Lokaal",
}

/** ahrefs = organische concurrenten; tracked = via de gevolgde zoekwoorden; manual = toegevoegd. */
export type CompetitorOrigin = "ahrefs" | "tracked" | "manual"

/** Waar Gedeeld en Overlap op gebaseerd zijn; één basis per momentopname. */
export type OverlapBasis = "ahrefs" | "tracked"

/** full = alles opnieuw ophalen; reuse = bewaarde gegevens hergebruiken ("Bijwerken"). */
export type RefreshMode = "full" | "reuse"

export type BlockedReason = "ahrefs_not_configured" | "no_website"

/**
 * ahrefs: ok | not_configured | error
 * prt: ok | not_configured | not_tracked | error
 * claude: ok | not_configured | error
 * profile: ok | empty
 */
export type SourceState = "ok" | "not_configured" | "not_tracked" | "empty" | "error"

/**
 * competitors: ok | empty | not_configured | error
 * heatmap: ok | no_profile | no_keywords | not_configured | error
 * summary: ok | not_configured | error | skipped
 */
export type SectionState =
  | "ok"
  | "empty"
  | "no_profile"
  | "no_keywords"
  | "not_configured"
  | "skipped"
  | "error"

export const TOP_COMPETITORS = 5
export const MAX_MANUAL_COMPETITORS = 10
/** Onder dit aantal zoekwoorden toont een onderwerp "te weinig zoekwoorden" (lege `cells`). */
export const MIN_TOPIC_KEYWORDS = 5

// --- Antwoord -------------------------------------------------------------------------------

export type SourceInfo = {
  state: SourceState
  message: string | null
}

export type Sources = {
  ahrefs: SourceInfo
  prt: SourceInfo
  claude: SourceInfo
  profile: SourceInfo
}

export type Kpis = {
  organic_keywords: { value: number | null; top10: number | null }
  /** `change_pct` t.o.v. de vorige maand; null = onbekend. */
  organic_traffic: { value: number | null; change_pct: number | null }
  domain_rating: { value: number | null; competitor_median: number | null }
  /** Gemiddelde overlap met de vijf. */
  top5_overlap: { pct: number | null; shared_avg: number | null }
}

/** Rij in de tabel, met de handmatige keuzes toegepast. */
export type CompetitorRow = {
  domain: string
  origin: CompetitorOrigin
  type: CompetitorType | null
  type_source: "ai" | "manual" | null
  excluded: boolean
  excluded_source: "ai" | "manual" | null
  /** Bijv. "vergelijkingssite" of "handmatig uitgesloten". */
  exclude_reason: string | null
  in_top5: boolean
  /** Handmatig toegevoegd na de laatste run: nog geen cijfers, eerst "Bijwerken". */
  pending: boolean
  domain_rating: number | null
  organic_keywords: number | null
  top10_keywords: number | null
  traffic: number | null
  shared: number
  overlap_pct: number
}

export type CompetitorsSection = {
  state: SectionState
  message: string | null
  /** Meetellende concurrenten op overlap aflopend, daarna de uitgesloten. */
  rows: CompetitorRow[]
}

export type HeatmapColumn = {
  domain: string
  is_customer: boolean
  /** Lijst afgekapt: het aandeel kan hoger zijn. */
  truncated: boolean
}

/** `level` 0..3: 0–9, 10–24, 25–49, ≥50 procent. */
export type HeatmapCell = {
  pct: number
  level: number
}

/** `cells` loopt gelijk met `Heatmap.columns`; leeg bij te weinig zoekwoorden. */
export type HeatmapRow = {
  topic: string
  kind: "service" | "local"
  keywords: number
  cells: HeatmapCell[]
}

export type Heatmap = {
  state: SectionState
  message: string | null
  columns: HeatmapColumn[]
  rows: HeatmapRow[]
  universe: { total: number; tracked: number; assigned: number }
}

export type Summary = {
  state: SectionState
  message: string | null
  paragraph: string | null
  /** Precies drie bij state "ok". */
  points: string[]
}

/** Antwoord van alle endpoints. Zonder momentopname is `kpis` null en zijn de secties leeg. */
export type CompetitorOverview = {
  status: OverviewStatus
  error_message: string | null
  customer_id: string
  domain: string | null
  country: string
  fetched_at: string | null
  expires_at: string | null
  /** Ahrefs-units van de laatste run. */
  units: number
  unit_cap: number
  /** Schatting voor een volledige verversing (voor bij de knop). */
  unit_estimate: number
  /** Er zijn keuzes gemaakt sinds de laatste run die de vijf raken: toon "Bijwerken". */
  dirty: boolean
  blocked_reason: BlockedReason | null
  blocked_message: string | null
  warnings: string[]
  overlap_basis: OverlapBasis
  /** Aantal gevolgde zoekwoorden in de steekproef bij basis "tracked". */
  tracked_sample: number
  sources: Sources | null
  kpis: Kpis | null
  competitors: CompetitorsSection
  heatmap: Heatmap
  summary: Summary
  ai_usage: AiUsage | null
  model: string | null
}

// --- Hulpfuncties ---------------------------------------------------------------------------

export function isOverviewActive(status: OverviewStatus) {
  return ACTIVE_OVERVIEW_STATUSES.includes(status)
}

// --- API ------------------------------------------------------------------------------------

const API_BASE = "/api/keywords"

export class KeywordCompetitorsError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "KeywordCompetitorsError"
  }
}

async function overviewFetch(path: string, init?: RequestInit): Promise<CompetitorOverview> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch {
    throw new KeywordCompetitorsError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as
    | (CompetitorOverview & { error?: string })
    | null
  if (!response.ok) {
    throw new KeywordCompetitorsError(payload?.error?.trim() || "Er ging iets mis.", response.status)
  }
  if (!payload) {
    throw new KeywordCompetitorsError("Onverwacht antwoord van de server.", response.status)
  }
  return payload
}

const overviewPath = (customerId: string) =>
  `/customers/${encodeURIComponent(customerId)}/competitors`

const jsonInit = (method: "POST" | "PATCH", body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
})

/** Het overzicht; zonder gegevens `status: "idle"`. Plant zelf een run in als het verlopen is. */
export function fetchCompetitorOverview(customerId: string) {
  return overviewFetch(overviewPath(customerId))
}

/** Start een verversing. 409 als er al een loopt, 400 als ophalen niet kan, 503 zonder wachtrij. */
export function refreshCompetitorOverview(customerId: string, mode: RefreshMode) {
  return overviewFetch(`${overviewPath(customerId)}/refresh`, jsonInit("POST", { mode }))
}

/** Voegt een concurrent handmatig toe; 400 bij het eigen domein, een dubbele of te veel. */
export function addManualCompetitor(customerId: string, domain: string) {
  return overviewFetch(`${overviewPath(customerId)}/manual`, jsonInit("POST", { domain }))
}

export function removeManualCompetitor(customerId: string, domain: string) {
  return overviewFetch(`${overviewPath(customerId)}/manual/remove`, jsonInit("POST", { domain }))
}

/**
 * Type en uitsluiting van één concurrent; beide velden worden altijd overschreven,
 * `null` = terug naar het oordeel van Claude.
 */
export function saveCompetitorChoice(
  customerId: string,
  choice: { domain: string; type: CompetitorType | null; excluded: boolean | null },
) {
  return overviewFetch(`${overviewPath(customerId)}/choice`, jsonInit("PATCH", choice))
}
