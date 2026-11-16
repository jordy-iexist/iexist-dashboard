import { Fragment } from "react"

import { MetricDelta } from "@/components/analytics/MetricDelta"
import type { MetricComparison } from "@/lib/analytics/api"
import { formatMetricValue, formatPct } from "@/lib/analytics/format"
import { joinLabels } from "@/lib/analytics/trend"
import { cn } from "@/lib/utils"

const th = "px-3 py-2 text-right font-medium align-bottom"
const td = "px-3 py-2 text-right tabular-nums whitespace-nowrap"
const sticky = "sticky left-0 z-[1] bg-card"

type Group = { group: string; label: string; rows: MetricComparison[] }

function groupRows(metrics: MetricComparison[]): Group[] {
  const groups: Group[] = []
  for (const metric of metrics) {
    let entry = groups.find((g) => g.group === metric.group)
    if (!entry) {
      entry = { group: metric.group, label: metric.group_label, rows: [] }
      groups.push(entry)
    }
    entry.rows.push(metric)
  }
  return groups
}

const isEmpty = (m: MetricComparison) => m.before == null && m.after == null

/**
 * Alle cijfers van scan A tegen scan B, per groep: metric / A / B / verschil / %.
 * Groepen die in geen van beide scans gemeten zijn, staan niet in de tabel maar
 * in één regel eronder.
 */
export function MetricCompareTable({
  metrics,
  labels,
  caption,
}: {
  metrics: MetricComparison[]
  labels: { before: string; after: string }
  caption?: string
}) {
  const groups = groupRows(metrics)
  const shown = groups.filter((g) => !g.rows.every(isEmpty))
  const skipped = groups.filter((g) => g.rows.every(isEmpty))

  return (
    <div className="space-y-2">
      {shown.length > 0 && (
        <div className="relative overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            {caption && <caption className="sr-only">{caption}</caption>}
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className={cn("px-3 py-2 text-left font-medium align-bottom", sticky, "bg-muted")}>
                  Cijfer
                </th>
                <th scope="col" className={th}>
                  <ScanHeading letter="A" label={labels.before} />
                </th>
                <th scope="col" className={th}>
                  <ScanHeading letter="B" label={labels.after} />
                </th>
                <th scope="col" className={cn(th, "whitespace-nowrap")}>
                  Verschil
                </th>
                <th scope="col" className={th} title="Verandering in procenten van A; leeg als A 0 of niet gemeten is">
                  %
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {shown.map((group) => (
                <Fragment key={group.group}>
                  <tr className="bg-muted/30">
                    <th
                      scope="colgroup"
                      colSpan={5}
                      className="px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                    >
                      {group.label}
                    </th>
                  </tr>
                  {group.rows.map((metric) => (
                    <tr key={metric.key}>
                      <th scope="row" className={cn("min-w-32 px-3 py-2 text-left font-normal sm:min-w-40", sticky)}>
                        {metric.label}
                      </th>
                      <ValueCell value={metric.before} metric={metric} />
                      <ValueCell value={metric.after} metric={metric} />
                      <td className={td}>
                        <MetricDelta
                          delta={metric.delta}
                          unit={metric.unit}
                          higherIsBetter={metric.higher_is_better}
                          className="justify-end"
                        />
                      </td>
                      <td className={cn(td, "text-muted-foreground")}>{formatPct(metric.pct)}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {skipped.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Niet gemeten in deze twee scans, en daarom weggelaten: {joinLabels(skipped.map((g) => g.label))}.
        </p>
      )}
    </div>
  )
}

function ScanHeading({ letter, label }: { letter: string; label: string }) {
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <span className="font-semibold text-foreground">{letter}</span>
      <span className="max-w-40 text-[11px] leading-tight font-normal">{label}</span>
    </span>
  )
}

function ValueCell({ value, metric }: { value: number | null; metric: MetricComparison }) {
  return (
    <td className={cn(td, value == null && "text-muted-foreground")}>
      {value == null ? <span title="Niet gemeten">–</span> : formatMetricValue(value, metric.unit)}
    </td>
  )
}
