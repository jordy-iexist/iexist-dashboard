"use client"

import Link from "next/link"
import { X } from "lucide-react"
import { useId } from "react"

import { ChartFrame, seriesColor, TrendLineChart, type ChartDatum } from "@/components/analytics/charts"
import type { TrendRequest } from "@/components/analytics/compare/CompareView"
import { FilterBar } from "@/components/analytics/FilterBar"
import { MetricTable } from "@/components/analytics/MetricTable"
import { EmptyState, ErrorNote, InfoNotes, Notice } from "@/components/analytics/states"
import { CompactStat, StatGrid } from "@/components/livegang/shared"
import type { MetricDef, TrendPoint } from "@/lib/analytics/api"
import { groupMetrics, MAX_TREND_METRICS } from "@/lib/analytics/compare"
import { formatAxisTick, formatDate, formatMetricValue, unitDescription } from "@/lib/analytics/format"
import { phasesLabel } from "@/lib/analytics/reports"
import { metricIndex, pointLabels, selectPoints, sourceNotes, sourcesForMetrics } from "@/lib/analytics/trend"
import type { LaunchCustomer } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const CHART_HEIGHT = 200
const selectClass =
  "h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30"

export type TrendCompareProps = {
  customers: LaunchCustomer[] | null
  customerId: string | null
  onCustomerChange: (customerId: string | null) => void
  trend: TrendRequest
  selected: string[]
  onSelectedChange: (keys: string[]) => void
}

/** Modus Trend: één klant, één tot vier metrics als kleine grafieken naast elkaar. */
export function TrendCompare({ customers, customerId, onCustomerChange, trend, selected, onSelectedChange }: TrendCompareProps) {
  const { data, error, loading } = trend

  return (
    <div className="space-y-6">
      <FilterBar
        customers={customers}
        filters={{ customerId, start: null, end: null, allScans: false }}
        onChange={(patch) => {
          if ("customerId" in patch) onCustomerChange(patch.customerId ?? null)
        }}
        showPeriod={false}
        showAllScans={false}
      />

      {!customerId ? (
        <EmptyState>Kies een klant om de trend te zien.</EmptyState>
      ) : error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Trend laden…</p>
      ) : (
        <TrendBody
          metrics={data.metrics}
          allPoints={data.points}
          customer={data.customer}
          selected={selected}
          onSelectedChange={onSelectedChange}
          loading={loading}
        />
      )}
    </div>
  )
}

function TrendBody({
  metrics,
  allPoints,
  customer,
  selected,
  onSelectedChange,
  loading,
}: {
  metrics: MetricDef[]
  allPoints: TrendPoint[]
  customer: { id: string; name: string; domain: string }
  selected: string[]
  onSelectedChange: (keys: string[]) => void
  loading: boolean
}) {
  const index = metricIndex(metrics)
  // Onbekende keys (oude link) vallen weg; blijft er niets over, dan de eerste metric.
  const known = selected.filter((key) => index.has(key))
  const chosen = (known.length > 0 ? known : metrics.slice(0, 1).map((m) => m.key))
    .map((key) => index.get(key))
    .filter((m): m is MetricDef => !!m)
  const points = selectPoints(allPoints, { phases: [1, 4], allScans: false })

  if (points.length === 0) {
    return (
      <EmptyState>
        {customer.name} heeft nog geen voltooide nulmeting of kwartaalscan.{" "}
        <Link
          href={`/dashboard/livegang/seo-geo/${encodeURIComponent(customer.id)}`}
          className="font-medium text-foreground underline underline-offset-4"
        >
          Naar de SEO/GEO-scan
        </Link>
      </EmptyState>
    )
  }

  const labels = pointLabels(points)
  const notes = sourceNotes(points, sourcesForMetrics(chosen), labels)
  const first = points[0]
  const last = points[points.length - 1]

  return (
    <div className={cn("space-y-6 transition-opacity", loading && "opacity-60")} aria-busy={loading}>
      <MetricPicker metrics={metrics} chosen={chosen} onChange={onSelectedChange} />

      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{customer.name}</span> · {customer.domain} · {points.length}{" "}
        {points.length === 1 ? "meting" : "metingen"},{" "}
        {points.length === 1 ? formatDate(first.date) : `${formatDate(first.date)} t/m ${formatDate(last.date)}`}
      </p>

      {points.length === 1 ? (
        <>
          <Notice>
            Er is nog maar één meting ({labels.get(last.scan_id)}). Het verloop verschijnt vanaf de tweede meting; tot die tijd
            staan hier de cijfers van die meting.
          </Notice>
          <StatGrid className={cn("grid-cols-2", chosen.length > 2 && "lg:grid-cols-4")}>
            {chosen.map((metric) => {
              const value = last.values[metric.key] ?? null
              return (
                <CompactStat
                  key={metric.key}
                  label={metric.label}
                  value={formatMetricValue(value, metric.unit)}
                  hint={
                    value != null
                      ? labels.get(last.scan_id)
                      : notMeasuredText(metric)
                  }
                />
              )
            })}
          </StatGrid>
          <InfoNotes notes={notes} />
        </>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {chosen.map((metric) => (
              <MetricTrendChart key={metric.key} metric={metric} points={points} labels={labels} loading={loading} />
            ))}
          </div>
          <InfoNotes notes={notes} />
          <MetricTable rows={chosen} points={points} labels={labels} caption={`Gekozen cijfers van ${customer.name} per meting`} />
        </>
      )}
    </div>
  )
}

function MetricTrendChart({
  metric,
  points,
  labels,
  loading,
}: {
  metric: MetricDef
  points: TrendPoint[]
  labels: Map<string, string>
  loading: boolean
}) {
  const data: ChartDatum[] = points.map((p) => ({
    x: p.scan_id,
    xLabel: labels.get(p.scan_id) ?? p.label,
    [metric.key]: p.values[metric.key] ?? null,
  }))
  const measured = points.filter((p) => p.values[metric.key] != null)
  const fixedScale = metric.unit === "percent" || metric.unit === "score"
  const description = `${metric.group_label} · ${unitDescription(metric)}`

  const empty = measured.length === 0 ? notMeasuredText(metric) : undefined

  return (
    <ChartFrame title={metric.label} description={description} height={CHART_HEIGHT} loading={loading} empty={empty}>
      <TrendLineChart
        data={data}
        series={[{ key: metric.key, label: metric.label, color: seriesColor(0) }]}
        formatValue={(value) => formatMetricValue(value, metric.unit)}
        formatTick={(value) => formatAxisTick(value, metric.unit)}
        yDomain={fixedScale ? [0, 100] : undefined}
        invertY={metric.unit === "position"}
        integerTicks={metric.unit === "count"}
        description={`${metric.label} over ${points.length} metingen, ${measured.length} gemeten. De exacte waarden staan in de tabel.`}
      />
    </ChartFrame>
  )
}

/** Waarom een metric bij de getoonde metingen niet gemeten is. */
function notMeasuredText(metric: MetricDef): string {
  const fromBoth = metric.phases.includes(1) && metric.phases.includes(4)
  return fromBoth ? "Niet gemeten bij deze metingen." : `Niet gemeten: komt alleen uit de ${phasesLabel(metric.phases)}.`
}

/** Gekozen metrics als chips (verwijderen) plus een gegroepeerde select om er een toe te voegen. */
function MetricPicker({
  metrics,
  chosen,
  onChange,
}: {
  metrics: MetricDef[]
  chosen: MetricDef[]
  onChange: (keys: string[]) => void
}) {
  const id = useId()
  const keys = chosen.map((m) => m.key)
  const full = keys.length >= MAX_TREND_METRICS
  const groups = groupMetrics(metrics)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-1 sm:w-72">
          <label htmlFor={`${id}-metric`} className="text-xs font-medium text-muted-foreground">
            Cijfer toevoegen ({keys.length} van {MAX_TREND_METRICS})
          </label>
          <select
            id={`${id}-metric`}
            className={selectClass}
            value=""
            disabled={full}
            onChange={(e) => e.target.value && onChange([...keys, e.target.value])}
          >
            <option value="">{full ? "Maximaal vier cijfers" : "Kies een cijfer…"}</option>
            {groups.map((group) => (
              <optgroup key={group.group} label={group.label}>
                {group.metrics.map((metric) => (
                  <option key={metric.key} value={metric.key} disabled={keys.includes(metric.key)}>
                    {metric.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
      </div>
      <ul className="flex flex-wrap gap-2" aria-label="Gekozen cijfers">
        {chosen.map((metric) => (
          <li
            key={metric.key}
            className="inline-flex max-w-full items-center gap-1 rounded-full border bg-card py-0.5 pr-1 pl-3 text-sm"
          >
            <span className="truncate">{metric.label}</span>
            <button
              type="button"
              className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
              onClick={() => onChange(keys.filter((key) => key !== metric.key))}
              disabled={keys.length <= 1}
              aria-label={`${metric.label} weghalen`}
              title={keys.length <= 1 ? "Er moet minstens één cijfer gekozen zijn" : "Weghalen"}
            >
              <X className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
