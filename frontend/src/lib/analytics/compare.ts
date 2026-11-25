/**
 * Analytics > Vergelijken: URL-state (`?modus=&a=&b=&metric=`) en pure helpers
 * voor de twee modi. De klant (`?klant=`) leest de pagina zelf. Geen React.
 */
import type { MetricDef, ScanRef, TrendPoint } from "@/lib/analytics/api"
import { formatShortDate } from "@/lib/analytics/format"

export const COMPARE_MODES = ["trend", "scans"] as const
export type CompareMode = (typeof COMPARE_MODES)[number]

export const MAX_TREND_METRICS = 4
export const DEFAULT_TREND_METRICS = ["issues_comparable", "ai_score", "domain_rating", "gsc_clicks"]

export type CompareState = {
  mode: CompareMode
  /** Gekozen scans (modus `scans`); `null` = standaard. */
  a: string | null
  b: string | null
  /** Metrics van de modus `trend` (1 tot 4). */
  trendMetrics: string[]
}

type RawSearchParams = { [key: string]: string | string[] | undefined }

function single(value: string | string[] | undefined): string | null {
  const v = Array.isArray(value) ? value[0] : value
  return v && v.trim() ? v.trim() : null
}

/**
 * Leest de beginstand uit (await-ed) `searchParams`. `metric` hoort bij de modus
 * in de URL; een onbekende modus (bijv. het vervallen `klanten`) wordt Trend.
 */
export function parseCompareParams(params: RawSearchParams): CompareState {
  const modeParam = single(params.modus)
  const mode = COMPARE_MODES.find((m) => m === modeParam) ?? "trend"
  const metrics = [...new Set((single(params.metric) ?? "").split(",").map((m) => m.trim()).filter(Boolean))]
  return {
    mode,
    a: single(params.a),
    b: single(params.b),
    trendMetrics: mode === "trend" && metrics.length > 0 ? metrics.slice(0, MAX_TREND_METRICS) : DEFAULT_TREND_METRICS,
  }
}

/** De state als URL-parameters voor `writeUrlParams`; alleen wat bij de huidige modus hoort (`klant` blijft staan). */
export function compareToUrlParams(state: CompareState): Record<string, string | null> {
  const trendMetrics = sameList(state.trendMetrics, DEFAULT_TREND_METRICS) ? null : state.trendMetrics.join(",")
  return {
    modus: state.mode === "trend" ? null : state.mode,
    a: state.mode === "scans" ? state.a : null,
    b: state.mode === "scans" ? state.b : null,
    metric: state.mode === "trend" ? trendMetrics : null,
  }
}

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index])
}

/** Metrics per groep, in de volgorde van de API (voor `<optgroup>`s). */
export function groupMetrics(metrics: MetricDef[]): { group: string; label: string; metrics: MetricDef[] }[] {
  const groups: { group: string; label: string; metrics: MetricDef[] }[] = []
  for (const metric of metrics) {
    let entry = groups.find((g) => g.group === metric.group)
    if (!entry) {
      entry = { group: metric.group, label: metric.group_label, metrics: [] }
      groups.push(entry)
    }
    entry.metrics.push(metric)
  }
  return groups
}

/**
 * Standaardpaar voor scan A tegen B: B = de laatste meting die voor zijn ronde
 * telt, A = de primaire meting daarvoor, anders de nulmeting, anders de scan
 * ervoor. `null` bij minder dan twee scans. `points` oplopend op datum.
 */
export function defaultScanPair(points: TrendPoint[]): { a: string; b: string } | null {
  if (points.length < 2) return null
  const primary = points.filter((p) => p.is_primary)
  const b = primary[primary.length - 1] ?? points[points.length - 1]
  const bIndex = points.indexOf(b)
  const earlier = points.slice(0, bIndex)
  const a =
    [...earlier].reverse().find((p) => p.is_primary) ??
    [...points].reverse().find((p) => p.phase === 1 && p !== b) ??
    earlier[earlier.length - 1] ??
    points.find((p) => p !== b)
  return a ? { a: a.scan_id, b: b.scan_id } : null
}

/** Labels voor de twee kanten; gelijke labels krijgen de datum (en zo nodig de tijd) erbij. */
export function scanPairLabels(a: ScanRef, b: ScanRef): { before: string; after: string } {
  if (a.label !== b.label) return { before: a.label, after: b.label }
  const dayA = formatShortDate(a.date)
  const dayB = formatShortDate(b.date)
  if (dayA !== dayB) return { before: `${a.label} · ${dayA}`, after: `${b.label} · ${dayB}` }
  return { before: `${a.label} · ${dayA} ${formatTime(a.date)}`, after: `${b.label} · ${dayB} ${formatTime(b.date)}` }
}

const timeFormat = new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit" })

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : timeFormat.format(date)
}
