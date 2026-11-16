/**
 * Grafiekthema: alleen CSS-variabelen uit `globals.css`, zodat licht/donker op
 * één plek wisselt. Kleuren volgen de reeks (vaste volgorde), nooit de rangorde.
 */

/** Categorisch palet in vaste volgorde (gevalideerd op kleurenblindheid; max. 5 reeksen). */
export const SERIES_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
] as const

export const MAX_SERIES = SERIES_COLORS.length

/** Statuskleuren: alleen voor reeksen die goed/waarschuwing/fout betekenen. */
export const STATUS_COLORS = {
  good: "var(--status-good)",
  warning: "var(--status-warning)",
  critical: "var(--status-critical)",
} as const

export type StatusTone = keyof typeof STATUS_COLORS

/** Kleur voor reeks `index` (0-gebaseerd). Buiten het palet: grijs, nooit een gegenereerde tint. */
export function seriesColor(index: number): string {
  return SERIES_COLORS[index] ?? "var(--muted-foreground)"
}

export const CHART = {
  /** Achtergrond van de kaart; gebruikt voor de 2px-ring om punten en de gaten tussen segmenten. */
  surface: "var(--card)",
  grid: "var(--border)",
  axis: "var(--border)",
  text: "var(--muted-foreground)",
  ink: "var(--foreground)",
  cursorFill: "var(--muted)",
  reference: "var(--muted-foreground)",
  fontSize: 11,
  lineWidth: 2,
  dotRadius: 4,
  maxBarSize: 24,
  barRadius: 4,
} as const

export const AXIS_TICK = { fill: CHART.text, fontSize: CHART.fontSize } as const

/** Rijhoogte van `RankBarChart`; gebruik `rankBarChartHeight(n)` voor de hoogte van de `ChartFrame`. */
export const RANK_ROW_HEIGHT = 32

export function rankBarChartHeight(count: number): number {
  return Math.max(1, count) * RANK_ROW_HEIGHT + 32
}

/**
 * Bovengrens van een as vanaf 0, afgerond zodat vier gelijke stappen ronde
 * getallen geven (340 → 400, 15.800 → 20.000, 2,6 → 4). Gebruik met `tickCount={5}`.
 */
export function niceAxisMax(dataMax: number, steps = 4): number {
  if (!Number.isFinite(dataMax) || dataMax <= 0) return 1
  const raw = dataMax / steps
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const normalized = raw / magnitude
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10
  return nice * magnitude * steps
}

export const AXIS_TICK_COUNT = 5
