import { Fragment } from "react"

import { MetricDelta } from "@/components/analytics/MetricDelta"
import type { MetricDef, TrendPoint } from "@/lib/analytics/api"
import { diff, formatMetricValue } from "@/lib/analytics/format"
import { cn } from "@/lib/utils"

const th = "px-3 py-2 text-right font-medium whitespace-nowrap"
const td = "px-3 py-2 text-right tabular-nums whitespace-nowrap"
const sticky = "sticky left-0 z-[1] bg-card"

export type MetricTableProps = {
  /** Rijen (metrics), in weergavevolgorde. */
  rows: MetricDef[]
  /** Kolommen (metingen), oplopend op datum. */
  points: TrendPoint[]
  /** Kolomkop per scan-id (zie `pointLabels`). */
  labels: Map<string, string>
  caption?: string
}

/**
 * Tabelweergave van een rapport: elke waarde ook zonder grafiek of tooltip
 * leesbaar. Laatste kolom: verschil tussen de eerste en de laatste gemeten waarde.
 */
export function MetricTable({ rows, points, labels, caption }: MetricTableProps) {
  if (rows.length === 0 || points.length === 0) return null
  const first = points[0]
  const last = points[points.length - 1]
  const showDiff = points.length > 1
  const multipleGroups = new Set(rows.map((r) => r.group)).size > 1
  const colSpan = points.length + 1 + (showDiff ? 1 : 0)

  return (
    <div className="relative overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>
            <th scope="col" className={cn("px-3 py-2 text-left font-medium", sticky, "bg-muted")}>
              Metric
            </th>
            {points.map((p) => (
              <th key={p.scan_id} scope="col" className={th}>
                {labels.get(p.scan_id) ?? p.label}
              </th>
            ))}
            {showDiff && (
              <th scope="col" className={th} title={`Eerste tegen laatste gemeten waarde (${labels.get(first.scan_id)} tot ${labels.get(last.scan_id)})`}>
                Verschil
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((metric, index) => {
            const groupStart = multipleGroups && (index === 0 || rows[index - 1].group !== metric.group)
            return (
              <Fragment key={metric.key}>
                {groupStart && (
                  <tr className="bg-muted/30">
                    <th
                      scope="colgroup"
                      colSpan={colSpan}
                      className="px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                    >
                      {metric.group_label}
                    </th>
                  </tr>
                )}
                <tr>
                  <th scope="row" className={cn("px-3 py-2 text-left font-normal", sticky)}>
                    {metric.label}
                  </th>
                  {points.map((p) => {
                    const value = p.values[metric.key]
                    return (
                      <td key={p.scan_id} className={cn(td, value == null && "text-muted-foreground")}>
                        {value == null ? <span title="Niet gemeten">–</span> : formatMetricValue(value, metric.unit)}
                      </td>
                    )
                  })}
                  {showDiff && (
                    <td className={td}>
                      <MetricDelta
                        delta={measuredDiff(metric.key, points)}
                        unit={metric.unit}
                        higherIsBetter={metric.higher_is_better}
                        className="justify-end"
                      />
                    </td>
                  )}
                </tr>
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Verschil tussen de eerste en de laatste gemeten waarde (gaten overslaan); `null` bij minder dan twee. */
function measuredDiff(key: string, points: TrendPoint[]): number | null {
  const measured = points.map((p) => p.values[key]).filter((v): v is number => v != null)
  return measured.length > 1 ? diff(measured[measured.length - 1], measured[0]) : null
}
