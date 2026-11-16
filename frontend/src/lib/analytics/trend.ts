/**
 * Pure helpers rond de trend-respons: punten selecteren, reeksen oplossen,
 * labels, regelset-markeringen en de brontoelichting. Geen React.
 */
import {
  GROUP_SOURCES,
  SOURCE_LABELS,
  type MetricDef,
  type RulesetBreak,
  type SourceKey,
  type SourceStatus,
  type TrendPoint,
} from "@/lib/analytics/api"
import { formatShortDate } from "@/lib/analytics/format"
import type { SeriesSpec, TableRowSpec } from "@/lib/analytics/reports"

export function metricIndex(metrics: MetricDef[]): Map<string, MetricDef> {
  return new Map(metrics.map((m) => [m.key, m]))
}

/** Punten van de gegeven fases; standaard alleen de primaire meting per ronde. */
export function selectPoints(points: TrendPoint[], { phases, allScans }: { phases: number[]; allScans: boolean }): TrendPoint[] {
  return points.filter((p) => phases.includes(p.phase) && (allScans || p.is_primary))
}

function hasAnyValue(metric: MetricDef, points: TrendPoint[]): boolean {
  return points.some((p) => p.values[metric.key] != null)
}

/**
 * Metrics van een reeks-spec. Vaste keys blijven staan (ook als ze leeg zijn,
 * zodat een gat zichtbaar is); bij een groep alleen de metrics met minstens
 * één gemeten waarde (dynamische categorieën).
 */
export function resolveSeries(spec: SeriesSpec, index: Map<string, MetricDef>, points: TrendPoint[]): MetricDef[] {
  if (Array.isArray(spec)) return spec.map((key) => index.get(key)).filter((m): m is MetricDef => !!m)
  return [...index.values()].filter((m) => m.group === spec.group && hasAnyValue(m, points))
}

export function resolveRows(rows: TableRowSpec[], index: Map<string, MetricDef>, points: TrendPoint[]): MetricDef[] {
  const seen = new Set<string>()
  const result: MetricDef[] = []
  for (const row of rows) {
    for (const metric of resolveSeries(typeof row === "string" ? [row] : row, index, points)) {
      if (seen.has(metric.key)) continue
      seen.add(metric.key)
      result.push(metric)
    }
  }
  return result
}

/** Label per scan; bij dubbele labels (meerdere scans in één ronde) met datum erachter. */
export function pointLabels(points: TrendPoint[]): Map<string, string> {
  const counts = new Map<string, number>()
  for (const p of points) counts.set(p.label, (counts.get(p.label) ?? 0) + 1)
  return new Map(
    points.map((p) => [p.scan_id, (counts.get(p.label) ?? 0) > 1 ? `${p.label} · ${formatShortDate(p.date)}` : p.label])
  )
}

/**
 * Regelset-wissels als markering vóór het eerste getoonde punt ná de wissel.
 * Valt de scan van `after_scan_id` buiten de selectie, dan telt zijn datum.
 */
export function breakMarkers(
  breaks: RulesetBreak[],
  allPoints: TrendPoint[],
  shown: TrendPoint[]
): { x: string; label: string; brk: RulesetBreak }[] {
  const result: { x: string; label: string; brk: RulesetBreak }[] = []
  const seen = new Set<string>()
  for (const brk of breaks) {
    const after = allPoints.find((p) => p.scan_id === brk.after_scan_id)
    if (!after) continue
    const afterTime = new Date(after.date).getTime()
    const next = shown.find((p) => new Date(p.date).getTime() > afterTime)
    // Geen getoond punt vóór de wissel: dan valt er in deze selectie niets te markeren.
    const hasBefore = shown.some((p) => new Date(p.date).getTime() <= afterTime)
    if (!next || !hasBefore || seen.has(next.scan_id)) continue
    seen.add(next.scan_id)
    result.push({ x: next.scan_id, label: "Nieuwe regelset", brk })
  }
  return result
}

/** Bronnen die de metrics van een rapportdeel voeden. */
export function sourcesForMetrics(metrics: MetricDef[]): SourceKey[] {
  const keys = new Set<SourceKey>()
  for (const m of metrics) {
    const source = GROUP_SOURCES[m.group]
    if (source) keys.add(source)
  }
  return [...keys]
}

export function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels[0] ?? ""
  return `${labels.slice(0, -1).join(", ")} en ${labels[labels.length - 1]}`
}

/**
 * Brontoelichting in gewone taal: waarom er een gat of een vlak stuk in de
 * grafiek zit. Eén zin per bron en status.
 */
export function sourceNotes(points: TrendPoint[], sources: SourceKey[], labels: Map<string, string>): string[] {
  const notes: string[] = []
  for (const source of sources) {
    const byStatus = new Map<SourceStatus, string[]>()
    for (const p of points) {
      const status = p.sources?.[source]
      if (!status || status === "ok") continue
      const list = byStatus.get(status) ?? []
      list.push(labels.get(p.scan_id) ?? p.label)
      byStatus.set(status, list)
    }
    const name = SOURCE_LABELS[source]
    for (const [status, list] of byStatus) {
      const at = joinLabels(list)
      switch (status) {
        case "not_connected":
          notes.push(
            `${name} was bij ${at} niet gekoppeld aan deze klant, dus daar ontbreekt een punt. Koppel de bron bij de klant om het vanaf de volgende scan te meten.`
          )
          break
        case "not_measured":
          notes.push(
            source === "cwv"
              ? `Core Web Vitals worden alleen bij de nulmeting gemeten; bij ${at} is daarom niets gemeten.`
              : `${name} wordt in de fase van ${at} niet gemeten, dus daar ontbreekt een punt.`
          )
          break
        case "reused":
          notes.push(
            `Bij ${at} zijn de ${name}-cijfers overgenomen van een eerdere meting (een herscan binnen 7 dagen haalt niets nieuws op). Een vlak stuk betekent daar dus niet dat er niets veranderd is.`
          )
          break
        case "error":
          notes.push(`Het ophalen van ${name} mislukte bij ${at}, dus daar ontbreekt een punt.`)
          break
      }
    }
  }
  return notes
}
