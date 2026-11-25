// Search Console-inzichten per klant: types van het backend-antwoord
// (`GET /api/customers/{id}/search-console-insights?days=7|28|90`), het faal-veilig
// inlezen daarvan en de adressen van het scherm. Vrij van server-code, zodat ook
// client-componenten (zoals de CSV-export) dit kunnen importeren.

import { customerHref } from "@/lib/active-customer"

/** Periodes die het scherm aanbiedt, in dagen. */
export const PERIOD_DAYS = [7, 28, 90] as const
export type PeriodDays = (typeof PERIOD_DAYS)[number]
/** Standaardperiode: het adres zonder querystring. */
export const DEFAULT_PERIOD_DAYS: PeriodDays = 28
/** Queryparameter met de periode (`?dagen=7`). */
export const PERIOD_PARAM = "dagen"

export type SearchConsoleState =
  | "ok"
  | "not_configured"
  | "token_expired"
  | "no_property"
  | "property_inaccessible"
  | "error"

export type InsightsPeriod = { start: string; end: string; days: number }

export type InsightsTotals = {
  clicks: number
  impressions: number
  /** Fractie 0–1. */
  ctr: number
  position: number | null
}

export type OpportunityRow = {
  query: string
  page: string
  impressions: number
  clicks: number
  /** Fractie 0–1. */
  ctr: number
  /** Fractie 0–1; null als de backend geen verwachting heeft. */
  expected_ctr: number | null
  position: number
  missed_clicks: number
  /** Andere pagina's die op deze zoekterm verschijnen (niet getoond). */
  other_pages: number
  /**
   * `improve_snippet_top`, `improve_snippet`, `improve_position` (eerst de positie
   * verbeteren; krijgt de link naar een concurrentieanalyse) of `check_intent`.
   */
  advice_code: string
  advice: string
}

export type OpportunitiesSection = {
  state: "ok" | "unavailable"
  message: string | null
  rows: OpportunityRow[]
  total: number
  potential_clicks_per_month: number | null
  brand_excluded: number
  truncated: boolean
  min_impressions: number
}

export type UntrackedState =
  | "ok"
  | "prt_not_tracked"
  | "prt_not_configured"
  | "prt_error"
  | "unavailable"

export type UntrackedRow = {
  query: string
  impressions: number
  clicks: number
  position: number | null
}

export type UntrackedSection = {
  state: UntrackedState
  message: string | null
  rows: UntrackedRow[]
  total: number
  tracked_keywords: number
}

export type DecliningRow = {
  page: string
  clicks: number
  clicks_prev: number
  delta: number
  pct: number | null
  impressions: number
  impressions_prev: number
  ctr: number | null
  ctr_prev: number | null
  position: number | null
  position_prev: number | null
  cause_code: string
  cause: string
}

export type DecliningSection = {
  state: "ok" | "unavailable"
  message: string | null
  rows: DecliningRow[]
  total: number
}

export type SearchConsoleInsights = {
  state: SearchConsoleState
  message: string | null
  days: number
  property: string | null
  property_source: "manual" | "auto" | null
  fetched_at: string | null
  period: InsightsPeriod | null
  previous: InsightsPeriod | null
  totals: InsightsTotals | null
  totals_previous: InsightsTotals | null
  opportunities: OpportunitiesSection
  untracked: UntrackedSection
  declining: DecliningSection
}

// --- Adressen -------------------------------------------------------------------------------

function isPeriodDays(value: number): value is PeriodDays {
  return (PERIOD_DAYS as readonly number[]).includes(value)
}

/** Periode uit `?dagen=`; alles wat geen 7, 28 of 90 is, wordt de standaard (28). */
export function parsePeriodDays(value: string | string[] | undefined): PeriodDays {
  const raw = Array.isArray(value) ? value[0] : value
  const days = Number(raw)
  return Number.isInteger(days) && isPeriodDays(days) ? days : DEFAULT_PERIOD_DAYS
}

/** Adres van het scherm; de standaardperiode zonder querystring. */
export function searchConsoleHref(customerId: string, days: PeriodDays = DEFAULT_PERIOD_DAYS) {
  const base = customerHref("searchConsole", customerId)
  return days === DEFAULT_PERIOD_DAYS ? base : `${base}?${PERIOD_PARAM}=${days}`
}

// --- Inlezen --------------------------------------------------------------------------------

const STATES: SearchConsoleState[] = [
  "ok",
  "not_configured",
  "token_expired",
  "no_property",
  "property_inaccessible",
  "error",
]
const UNTRACKED_STATES: UntrackedState[] = [
  "ok",
  "prt_not_tracked",
  "prt_not_configured",
  "prt_error",
  "unavailable",
]

type Json = Record<string, unknown>

function asObject(value: unknown): Json | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function count(value: unknown): number {
  return Math.max(0, num(value) ?? 0)
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

function list<T>(value: unknown, parse: (item: Json) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const object = asObject(item)
    const parsed = object ? parse(object) : null
    return parsed ? [parsed] : []
  })
}

function parsePeriod(value: unknown): InsightsPeriod | null {
  const object = asObject(value)
  const start = text(object?.start)
  const end = text(object?.end)
  if (!object || !start || !end) return null
  return { start, end, days: count(object.days) }
}

function parseTotals(value: unknown): InsightsTotals | null {
  const object = asObject(value)
  if (!object) return null
  const clicks = num(object.clicks)
  const impressions = num(object.impressions)
  if (clicks === null || impressions === null) return null
  return {
    clicks,
    impressions,
    ctr: num(object.ctr) ?? (impressions > 0 ? clicks / impressions : 0),
    position: num(object.position),
  }
}

function parseOpportunityRow(row: Json): OpportunityRow | null {
  const query = text(row.query)
  const page = text(row.page)
  const position = num(row.position)
  if (!query || !page || position === null) return null
  const impressions = count(row.impressions)
  const clicks = count(row.clicks)
  return {
    query,
    page,
    impressions,
    clicks,
    ctr: num(row.ctr) ?? (impressions > 0 ? clicks / impressions : 0),
    expected_ctr: num(row.expected_ctr),
    position,
    missed_clicks: count(row.missed_clicks),
    other_pages: count(row.other_pages),
    advice_code: text(row.advice_code) ?? "",
    advice: text(row.advice) ?? "",
  }
}

function parseUntrackedRow(row: Json): UntrackedRow | null {
  const query = text(row.query)
  if (!query) return null
  return {
    query,
    impressions: count(row.impressions),
    clicks: count(row.clicks),
    position: num(row.position),
  }
}

function parseDecliningRow(row: Json): DecliningRow | null {
  const page = text(row.page)
  if (!page) return null
  const clicks = count(row.clicks)
  const clicksPrev = count(row.clicks_prev)
  return {
    page,
    clicks,
    clicks_prev: clicksPrev,
    delta: num(row.delta) ?? clicks - clicksPrev,
    pct: num(row.pct),
    impressions: count(row.impressions),
    impressions_prev: count(row.impressions_prev),
    ctr: num(row.ctr),
    ctr_prev: num(row.ctr_prev),
    position: num(row.position),
    position_prev: num(row.position_prev),
    cause_code: text(row.cause_code) ?? "",
    cause: text(row.cause) ?? "",
  }
}

function parseOpportunities(value: unknown): OpportunitiesSection {
  const object = asObject(value)
  const rows = list(object?.rows, parseOpportunityRow)
  return {
    state: object?.state === "ok" ? "ok" : "unavailable",
    message: text(object?.message),
    rows,
    total: Math.max(count(object?.total), rows.length),
    potential_clicks_per_month: num(object?.potential_clicks_per_month),
    brand_excluded: count(object?.brand_excluded),
    truncated: object?.truncated === true,
    min_impressions: count(object?.min_impressions),
  }
}

function parseUntracked(value: unknown): UntrackedSection {
  const object = asObject(value)
  const state = UNTRACKED_STATES.includes(object?.state as UntrackedState)
    ? (object?.state as UntrackedState)
    : "unavailable"
  const rows = list(object?.rows, parseUntrackedRow)
  return {
    state,
    message: text(object?.message),
    rows,
    total: Math.max(count(object?.total), rows.length),
    tracked_keywords: count(object?.tracked_keywords),
  }
}

function parseDeclining(value: unknown): DecliningSection {
  const object = asObject(value)
  const rows = list(object?.rows, parseDecliningRow)
  return {
    state: object?.state === "ok" ? "ok" : "unavailable",
    message: text(object?.message),
    rows,
    total: Math.max(count(object?.total), rows.length),
  }
}

/** Antwoord bij een mislukte aanroep of een onleesbaar antwoord: `state: "error"`. */
export function failedInsights(days: number, message: string | null = null): SearchConsoleInsights {
  return {
    state: "error",
    message,
    days,
    property: null,
    property_source: null,
    fetched_at: null,
    period: null,
    previous: null,
    totals: null,
    totals_previous: null,
    opportunities: parseOpportunities(null),
    untracked: parseUntracked(null),
    declining: parseDeclining(null),
  }
}

/**
 * Leest het antwoord van de backend in. Ontbrekende of ongeldige velden krijgen een
 * veilige waarde; een onbekende `state` of `state: "ok"` zonder totalen wordt "error".
 */
export function parseSearchConsoleInsights(payload: unknown, days: number): SearchConsoleInsights {
  const object = asObject(payload)
  const state = object?.state
  if (!object || !STATES.includes(state as SearchConsoleState)) {
    return failedInsights(days)
  }
  const totals = parseTotals(object.totals)
  if (state === "ok" && !totals) return failedInsights(days, text(object.message))

  const source = object.property_source
  return {
    state: state as SearchConsoleState,
    message: text(object.message),
    days: num(object.days) ?? days,
    property: text(object.property),
    property_source: source === "manual" || source === "auto" ? source : null,
    fetched_at: text(object.fetched_at),
    period: parsePeriod(object.period),
    previous: parsePeriod(object.previous),
    totals,
    totals_previous: parseTotals(object.totals_previous),
    opportunities: parseOpportunities(object.opportunities),
    untracked: parseUntracked(object.untracked),
    declining: parseDeclining(object.declining),
  }
}
