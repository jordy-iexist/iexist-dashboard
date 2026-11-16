/**
 * Opmaak van analytics-cijfers per eenheid (nl-NL). `null` = niet gemeten en
 * wordt "–", nooit 0.
 */
import type { MetricDef, MetricUnit } from "@/lib/analytics/api"

export const EMPTY_VALUE = "–"

const integer = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 0 })
const oneDecimal = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 1 })
const compact = new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 })

/** Exacte waarde met eenheid, voor tegels, tabellen en tooltips. */
export function formatMetricValue(value: number | null | undefined, unit: MetricUnit): string {
  if (value == null || Number.isNaN(value)) return EMPTY_VALUE
  switch (unit) {
    case "percent":
      return `${oneDecimal.format(value)}%`
    case "ms":
      return `${integer.format(value)} ms`
    case "position":
      return oneDecimal.format(value)
    case "score":
      return oneDecimal.format(value)
    case "count":
    default:
      return Number.isInteger(value) ? integer.format(value) : oneDecimal.format(value)
  }
}

/** Korte notatie voor as-labels: volledig onder 10.000, daarboven compact (12,3K). */
export function formatAxisTick(value: number, unit: MetricUnit): string {
  if (!Number.isFinite(value)) return ""
  if (unit === "percent") return `${oneDecimal.format(value)}%`
  if (unit === "ms") return Math.abs(value) >= 10_000 ? `${compact.format(value)} ms` : `${integer.format(value)} ms`
  return Math.abs(value) >= 10_000 ? compact.format(value) : oneDecimal.format(value)
}

/** Verschil met teken; procenten als procentpunten ("+2,1 pp"). */
export function formatDelta(delta: number, unit: MetricUnit): string {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±"
  const abs = Math.abs(delta)
  switch (unit) {
    case "percent":
      return `${sign}${oneDecimal.format(abs)} pp`
    case "ms":
      return `${sign}${integer.format(abs)} ms`
    case "position":
    case "score":
      return `${sign}${oneDecimal.format(abs)}`
    case "count":
    default:
      return `${sign}${Number.isInteger(abs) ? integer.format(abs) : oneDecimal.format(abs)}`
  }
}

/** Procentuele verandering met teken ("+12,5%"); `null` = niet te berekenen. */
export function formatPct(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return EMPTY_VALUE
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±"
  return `${sign}${oneDecimal.format(Math.abs(pct))}%`
}

export type DeltaTone = "good" | "bad" | "neutral"

/** Goed of slecht, afhankelijk van de richting van de metric (`null` = geen oordeel). */
export function deltaTone(delta: number | null, higherIsBetter: boolean | null): DeltaTone {
  if (delta == null || delta === 0 || higherIsBetter == null) return "neutral"
  return delta > 0 === higherIsBetter ? "good" : "bad"
}

/** Verschil tussen twee waarden; `null` als een van beide niet gemeten is. */
export function diff(after: number | null | undefined, before: number | null | undefined): number | null {
  if (after == null || before == null) return null
  return after - before
}

const dateFormat = new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium" })
const shortDateFormat = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short" })

export function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? EMPTY_VALUE : dateFormat.format(date)
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? EMPTY_VALUE : shortDateFormat.format(date)
}

/** Korte omschrijving van de eenheid, voor schermlezers en toelichtingen. */
export function unitDescription(metric: Pick<MetricDef, "unit" | "higher_is_better">): string {
  const unit = {
    count: "aantal",
    percent: "percentage",
    score: "score",
    ms: "milliseconden",
    position: "gemiddelde positie",
  }[metric.unit]
  if (metric.higher_is_better === true) return `${unit}, hoger is beter`
  if (metric.higher_is_better === false) return `${unit}, lager is beter`
  return unit
}
