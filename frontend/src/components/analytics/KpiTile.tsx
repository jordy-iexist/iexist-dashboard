import { MetricDelta } from "@/components/analytics/MetricDelta"
import { CompactStat } from "@/components/livegang/shared"
import type { MetricDef, TrendPoint } from "@/lib/analytics/api"
import { diff, formatMetricValue } from "@/lib/analytics/format"

/** Tegel met de waarde van `metric` bij de laatste meting en het verschil t.o.v. de meting ervoor. */
export function KpiTile({
  metric,
  last,
  previous,
  labels,
}: {
  metric: MetricDef
  last: TrendPoint
  previous: TrendPoint | null
  labels: Map<string, string>
}) {
  const value = last.values[metric.key] ?? null
  const delta = previous ? diff(value, previous.values[metric.key]) : null
  const hint = previous
    ? `${labels.get(last.scan_id)}, t.o.v. ${labels.get(previous.scan_id)}`
    : labels.get(last.scan_id)
  return (
    <CompactStat
      label={metric.label}
      hint={value == null ? `Niet gemeten bij ${labels.get(last.scan_id)}` : hint}
      value={
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span>{formatMetricValue(value, metric.unit)}</span>
          {previous && delta != null && (
            <MetricDelta delta={delta} unit={metric.unit} higherIsBetter={metric.higher_is_better} className="text-xs" />
          )}
        </span>
      }
    />
  )
}
