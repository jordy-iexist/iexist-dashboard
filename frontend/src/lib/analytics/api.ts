/**
 * Analytics: types en fetch-functies voor de trend-API van de livegang-checklist
 * (`GET /analytics/customers/{id}/trend`). Alleen fase 1 (nulmeting) en fase 4
 * (kwartaalscan) leveren punten; `null` betekent "niet gemeten", nooit 0.
 */
import { apiFetch, type LaunchCustomer, type QuarterlyComparison } from "@/lib/launch-checklist"

export type MetricUnit = "count" | "percent" | "score" | "ms" | "position"

export type MetricDef = {
  key: string
  label: string
  group: string
  group_label: string
  unit: MetricUnit
  /** `null`: geen richting (bijv. aantal pagina's). */
  higher_is_better: boolean | null
  phases: number[]
}

export type SourceKey = "ahrefs" | "search_console" | "bing" | "cwv" | "proranktracker"
export type SourceStatus = "ok" | "reused" | "not_measured" | "not_connected" | "error"

export type TrendPoint = {
  scan_id: string
  phase: number
  /** Ronde, bijv. "2026-Q4". */
  period: string | null
  /** Leesbaar label, bijv. "Nulmeting mrt 2026" of "Q4 2026". */
  label: string
  /** ISO-datum van de scan. */
  date: string
  ruleset: number
  /** De meting die voor deze ronde telt (laatste voltooide scan per kwartaal). */
  is_primary: boolean
  sources: Partial<Record<SourceKey, SourceStatus>>
  values: Record<string, number | null>
}

/** Regelset-wissel: na `after_scan_id` telt de scan met regelset `to` i.p.v. `from`. */
export type RulesetBreak = { after_scan_id: string; from: number; to: number }

export type TrendResponse = {
  customer: { id: string; name: string; domain: string }
  metrics: MetricDef[]
  /** Oplopend op datum. */
  points: TrendPoint[]
  breaks: RulesetBreak[]
}

export type TrendRange = { start?: string | null; end?: string | null }

export function fetchTrend(customerId: string, range: TrendRange = {}, init?: RequestInit): Promise<TrendResponse> {
  const query = new URLSearchParams()
  if (range.start) query.set("start", range.start)
  if (range.end) query.set("end", range.end)
  const qs = query.toString()
  return apiFetch<TrendResponse>(`/analytics/customers/${encodeURIComponent(customerId)}/trend${qs ? `?${qs}` : ""}`, init)
}

// --- scan A tegen B (`GET /analytics/compare`) -----------------------------------

/** Scan zoals compare en benchmark hem noemen. */
export type ScanRef = { scan_id: string; phase: number; period: string; label: string; date: string }

export type MetricComparison = Omit<MetricDef, "phases"> & {
  before: number | null
  after: number | null
  delta: number | null
  /** Procentuele verandering; `null` als `before` 0 of niet gemeten is. */
  pct: number | null
}

/** De delen `ai`..`rankings` hebben de vorm van de fase 4-vergelijking (`QuarterlyComparison`). */
export type CompareResponse = {
  /** Oudste scan; de server zet A en B op datum, ongeacht de volgorde van de aanvraag. */
  a: ScanRef
  b: ScanRef
  /** Altijd alle scan-metrics, ook als beide waarden `null` zijn. */
  metrics: MetricComparison[]
  ai: QuarterlyComparison["ai"] | null
  issues: QuarterlyComparison["issues"] | null
  pages: QuarterlyComparison["pages"] | null
  ahrefs: QuarterlyComparison["ahrefs"]
  rankings: QuarterlyComparison["rankings"]
  /** Toelichting in gewone taal (niet gemeten, hergebruikt, regelset-wissel). */
  notes: string[]
}

export function fetchCompare(a: string, b: string, init?: RequestInit): Promise<CompareResponse> {
  const query = new URLSearchParams({ a, b })
  return apiFetch<CompareResponse>(`/analytics/compare?${query}`, init)
}

// --- klanten onderling (`GET /analytics/benchmark`) -------------------------------

export type BenchmarkRow = {
  customer: { id: string; name: string; domain: string }
  /** Laatste voltooide nulmeting of kwartaalscan; `null` = alleen checklist-voortgang. */
  scan: ScanRef | null
  values: Record<string, number | null>
}

export type MetricSummary = {
  median: number | null
  p25: number | null
  p75: number | null
  min: number | null
  max: number | null
  /** Aantal klanten met een waarde. */
  n: number
}

export type BenchmarkResponse = {
  metrics: MetricDef[]
  rows: BenchmarkRow[]
  summary: Record<string, MetricSummary>
}

export function fetchBenchmark(init?: RequestInit): Promise<BenchmarkResponse> {
  return apiFetch<BenchmarkResponse>("/analytics/benchmark", init)
}

/** Groep met de huidige checklist-voortgang (fase 2, 3, 5): hangt niet aan een scandatum. */
export const CHECKLIST_GROUP = "checklist"

/** Klanten voor de klantkiezer (zelfde lijst als de livegang-overzichten). */
export function fetchAnalyticsCustomers(): Promise<LaunchCustomer[]> {
  return apiFetch<{ customers: LaunchCustomer[] }>("/customers").then((data) => data.customers)
}

/** Welke externe bron een metric-groep voedt; bepaalt welke brontoelichting een rapport toont. */
export const GROUP_SOURCES: Partial<Record<string, SourceKey>> = {
  ahrefs: "ahrefs",
  gsc: "search_console",
  bing: "bing",
  cwv: "cwv",
  prt: "proranktracker",
}

export const SOURCE_LABELS: Record<SourceKey, string> = {
  ahrefs: "Ahrefs",
  search_console: "Google Search Console",
  bing: "Bing Webmaster Tools",
  cwv: "Core Web Vitals",
  proranktracker: "ProRankTracker",
}

// --- filters in de URL ------------------------------------------------------

/** Filters van een analytics-pagina: `?klant=<id>&van=YYYY-MM-DD&tot=YYYY-MM-DD&alle=1`. */
export type AnalyticsFilters = {
  customerId: string | null
  start: string | null
  end: string | null
  /** Ook de niet-primaire scans tonen (meer dan één punt per ronde). */
  allScans: boolean
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

type RawSearchParams = { [key: string]: string | string[] | undefined }

function single(value: string | string[] | undefined): string | null {
  const v = Array.isArray(value) ? value[0] : value
  return v && v.trim() ? v.trim() : null
}

/** Leest de filters uit (await-ed) `searchParams`; werkt op server en client. */
export function parseAnalyticsFilters(params: RawSearchParams): AnalyticsFilters {
  const start = single(params.van)
  const end = single(params.tot)
  return {
    customerId: single(params.klant),
    start: start && ISO_DATE.test(start) ? start : null,
    end: end && ISO_DATE.test(end) ? end : null,
    allScans: single(params.alle) === "1",
  }
}

/** Filters als URL-parameters voor `writeUrlParams` (`null` = verwijderen). */
export function filtersToUrlParams(filters: AnalyticsFilters): Record<string, string | null> {
  return {
    klant: filters.customerId,
    van: filters.start,
    tot: filters.end,
    alle: filters.allScans ? "1" : null,
  }
}
