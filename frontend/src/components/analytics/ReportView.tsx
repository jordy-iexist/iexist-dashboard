"use client"

import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { useEffect, useState } from "react"

import {
  ChartFrame,
  MAX_SERIES,
  RankBarChart,
  rankBarChartHeight,
  seriesColor,
  STATUS_COLORS,
  StackedBarChart,
  TrendLineChart,
  type ChartDatum,
  type ChartSeries,
  type StatusTone,
} from "@/components/analytics/charts"
import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { FilterBar } from "@/components/analytics/FilterBar"
import { KpiTile } from "@/components/analytics/KpiTile"
import { MetricTable } from "@/components/analytics/MetricTable"
import { EmptyState, ErrorNote, InfoNotes, Notice } from "@/components/analytics/states"
import { StatGrid } from "@/components/livegang/shared"
import {
  fetchTrend,
  filtersToUrlParams,
  type AnalyticsFilters,
  type MetricDef,
  type TrendPoint,
  type TrendResponse,
} from "@/lib/analytics/api"
import { formatAxisTick, formatDate, formatMetricValue } from "@/lib/analytics/format"
import { getReport, phasesLabel, type ChartDef, type ReportDef, type ReportSection } from "@/lib/analytics/reports"
import {
  breakMarkers,
  joinLabels,
  metricIndex,
  pointLabels,
  resolveRows,
  resolveSeries,
  selectPoints,
  sourceNotes,
  sourcesForMetrics,
} from "@/lib/analytics/trend"
import { writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const LINE_HEIGHT = 220
const BAR_HEIGHT = 260
const STATUS_ORDER: StatusTone[] = ["good", "warning", "critical"]

const KPI_COLS: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
  6: "lg:grid-cols-6",
}

type TrendResult = { key: string; data?: TrendResponse; error?: string }

function requestKey(filters: AnalyticsFilters): string | null {
  if (!filters.customerId) return null
  if (filters.start && filters.end && filters.start > filters.end) return null
  return `${filters.customerId}|${filters.start ?? ""}|${filters.end ?? ""}`
}

/**
 * Rendert elk rapport uit `REPORTS`: filterbalk, KPI-tegels, grafieken, tabel
 * en brontoelichting. Filters staan in de URL (`?klant=&van=&tot=&alle=1`); de
 * klant komt uit het adres en wisselt alleen via de klantkiezer in de sidebar.
 */
export function ReportView({ slug, initialFilters }: { slug: string; initialFilters: AnalyticsFilters }) {
  const report = getReport(slug)
  const [filters, setFilters] = useState<AnalyticsFilters>(initialFilters)
  const [result, setResult] = useState<TrendResult | null>(null)

  const key = requestKey(filters)
  const { customerId, start, end } = filters
  useEffect(() => {
    if (!key || !customerId) return
    let cancelled = false
    fetchTrend(customerId, { start, end })
      .then((data) => !cancelled && setResult({ key, data }))
      .catch((err: Error) => !cancelled && setResult({ key, error: err.message }))
    return () => {
      cancelled = true
    }
  }, [key, customerId, start, end])

  function updateFilters(patch: Partial<AnalyticsFilters>) {
    setFilters((current) => {
      const next = { ...current, ...patch }
      writeUrlParams(filtersToUrlParams(next))
      return next
    })
  }

  if (!report) return null

  const loading = key !== null && result?.key !== key
  // Herladen voor dezelfde klant: de vorige weergave blijft (gedimd) staan.
  const data = result?.data && result.data.customer.id === filters.customerId ? result.data : null
  const error = result?.key === key ? result?.error : undefined
  const query = filters.customerId ? `?klant=${encodeURIComponent(filters.customerId)}` : ""

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link
          href={`${ANALYTICS_BASE_URL}/rapporten${query}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Alle rapporten
        </Link>
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
            <report.icon className="size-4" />
          </span>
          <div className="min-w-0 space-y-0.5">
            <h2 className="text-xl font-bold tracking-tight">{report.title}</h2>
            <p className="text-sm text-muted-foreground">{report.description}</p>
          </div>
        </div>
      </div>

      <FilterBar filters={filters} onChange={updateFilters} />

      {key === null ? null : error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Rapport laden…</p>
      ) : (
        <ReportBody report={report} trend={data} filters={filters} loading={loading} />
      )}
    </div>
  )
}

function ReportBody({
  report,
  trend,
  filters,
  loading,
}: {
  report: ReportDef
  trend: TrendResponse
  filters: AnalyticsFilters
  loading: boolean
}) {
  const hasPeriod = !!(filters.start || filters.end)
  const scanUrl = `/dashboard/livegang/seo-geo/${encodeURIComponent(trend.customer.id)}`

  if (trend.points.length === 0) {
    return (
      <EmptyState>
        {hasPeriod ? (
          <>Voor {trend.customer.name} is er geen nulmeting of kwartaalscan in de gekozen periode.</>
        ) : (
          <>
            {trend.customer.name} heeft nog geen voltooide nulmeting of kwartaalscan.{" "}
            <Link href={scanUrl} className="font-medium text-foreground underline underline-offset-4">
              Naar de SEO/GEO-scan
            </Link>
          </>
        )}
      </EmptyState>
    )
  }

  const main: ReportSection = {
    title: report.title,
    phases: report.phases,
    kpis: report.kpis,
    charts: report.charts,
    table: report.table,
    notes: report.notes,
  }
  const shownPoints = selectPoints(trend.points, { phases: report.phases, allScans: filters.allScans })

  return (
    <div className={cn("space-y-8 transition-opacity", loading && "opacity-60")} aria-busy={loading}>
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{trend.customer.name}</span> · {trend.customer.domain}
        {shownPoints.length > 0 && (
          <>
            {" "}
            · {shownPoints.length} {shownPoints.length === 1 ? "meting" : "metingen"},{" "}
            {shownPoints.length === 1
              ? formatDate(shownPoints[0].date)
              : `${formatDate(shownPoints[0].date)} t/m ${formatDate(shownPoints[shownPoints.length - 1].date)}`}
          </>
        )}
      </p>
      <SectionView section={main} isMain report={report} trend={trend} filters={filters} loading={loading} />
      {report.sections?.map((section) => (
        <SectionView
          key={section.title}
          section={section}
          report={report}
          trend={trend}
          filters={filters}
          loading={loading}
        />
      ))}
    </div>
  )
}

function SectionView({
  section,
  isMain = false,
  report,
  trend,
  filters,
  loading,
}: {
  section: ReportSection
  isMain?: boolean
  report: ReportDef
  trend: TrendResponse
  filters: AnalyticsFilters
  loading: boolean
}) {
  const phases = section.phases ?? report.phases
  const points = selectPoints(trend.points, { phases, allScans: filters.allScans })
  const index = metricIndex(trend.metrics)
  const heading = !isMain && (
    <div className="space-y-1">
      <h3 className="text-lg font-bold tracking-wide">{section.title}</h3>
      {section.description && <p className="text-sm text-muted-foreground">{section.description}</p>}
    </div>
  )

  if (points.length === 0) {
    const hasPeriod = !!(filters.start || filters.end)
    const onlyQuarterly = phases.length === 1 && phases[0] === 4
    return (
      <section className="space-y-3">
        {heading}
        <EmptyState>
          {isMain ? "Dit rapport" : "Dit onderdeel"} gebruikt cijfers uit de {phasesLabel(phases)}.{" "}
          {hasPeriod
            ? `Voor ${trend.customer.name} is die er niet in de gekozen periode.`
            : onlyQuarterly
              ? `${trend.customer.name} heeft nog alleen een nulmeting; na de eerste kwartaalscan verschijnen hier cijfers.`
              : `Voor ${trend.customer.name} is die er nog niet.`}
        </EmptyState>
      </section>
    )
  }

  const labels = pointLabels(points)
  const last = points[points.length - 1]
  const previous = points.length > 1 ? points[points.length - 2] : null
  const kpis = resolveSeries(section.kpis, index, points)
  const rows = resolveRows(section.table, index, points)
  const chartMetrics = section.charts.flatMap((chart) => resolveSeries(chart.series, index, points))
  const notes = [
    ...sourceNotes(points, sourcesForMetrics([...kpis, ...chartMetrics, ...rows]), labels),
    ...(section.notes ?? []),
  ]
  const timeCharts = section.charts.filter((chart) => !isLatestOnly(chart, index, points))

  return (
    <section className="space-y-4">
      {heading}

      {kpis.length > 0 && (
        <StatGrid className={cn("grid-cols-2 sm:grid-cols-3", KPI_COLS[Math.min(kpis.length, 6)])}>
          {kpis.map((metric) => (
            <KpiTile key={metric.key} metric={metric} last={last} previous={previous} labels={labels} />
          ))}
        </StatGrid>
      )}

      {points.length === 1 && timeCharts.length > 0 && (
        <Notice>
          Er is nog maar één meting ({labels.get(last.scan_id)}). Het verloop verschijnt vanaf de tweede meting; de cijfers
          staan in de tegels en de tabel.
        </Notice>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {section.charts.map((chart) => (
          <ReportChart
            key={chart.title}
            chart={chart}
            index={index}
            points={points}
            allPoints={trend.points}
            breaks={trend.breaks}
            labels={labels}
            loading={loading}
          />
        ))}
      </div>

      <InfoNotes notes={notes} />

      <MetricTable rows={rows} points={points} labels={labels} caption={`${section.title} per meting`} />
    </section>
  )
}

/** Een groep met meer reeksen dan het palet aankan, toont alleen de laatste meting. */
function isLatestOnly(chart: ChartDef, index: Map<string, MetricDef>, points: TrendPoint[]): boolean {
  return !!chart.latestOnly || resolveSeries(chart.series, index, points).length > MAX_SERIES
}

function ReportChart({
  chart,
  index,
  points,
  allPoints,
  breaks,
  labels,
  loading,
}: {
  chart: ChartDef
  index: Map<string, MetricDef>
  points: TrendPoint[]
  allPoints: TrendPoint[]
  breaks: TrendResponse["breaks"]
  labels: Map<string, string>
  loading: boolean
}) {
  const metrics = resolveSeries(chart.series, index, points)
  if (metrics.length === 0) return null
  const unit = metrics[0].unit
  const formatValue = (value: number, key: string) => formatMetricValue(value, index.get(key)?.unit ?? unit)
  const formatTick = (value: number) => formatAxisTick(value, unit)
  const last = points[points.length - 1]
  const lastLabel = labels.get(last.scan_id) ?? last.label

  if (isLatestOnly(chart, index, points)) {
    const items = metrics.map((m) => ({ key: m.key, label: m.label, value: last.values[m.key] ?? null }))
    const measured = items.some((item) => item.value != null)
    return (
      <ChartFrame
        title={chart.title}
        description={chart.description ?? lastLabel}
        height={rankBarChartHeight(items.length)}
        loading={loading}
        empty={measured ? undefined : `Niet gemeten bij ${lastLabel}.`}
      >
        <RankBarChart
          items={items}
          formatValue={(value) => formatValue(value, metrics[0].key)}
          formatTick={formatTick}
          seriesLabel={lastLabel}
          domain={chart.yDomain}
          description={`${chart.title}, ${lastLabel}: ${items
            .map((item) => `${item.label} ${item.value == null ? "niet gemeten" : formatValue(item.value, item.key)}`)
            .join("; ")}`}
        />
      </ChartFrame>
    )
  }

  // Eén punt: geen lijn of staafreeks die een verloop suggereert (tegels + tabel volstaan).
  if (points.length < 2) return null

  const series: ChartSeries[] = metrics.map((m, i) => ({
    key: m.key,
    label: m.label,
    color: chart.palette === "status" ? STATUS_COLORS[STATUS_ORDER[i] ?? "critical"] : seriesColor(i),
  }))
  const data: ChartDatum[] = points.map((p) => {
    const datum: ChartDatum = { x: p.scan_id, xLabel: labels.get(p.scan_id) ?? p.label }
    for (const m of metrics) datum[m.key] = p.values[m.key] ?? null
    return datum
  })
  const measured = data.some((d) => metrics.some((m) => d[m.key] != null))
  const markers = chart.markBreaks ? breakMarkers(breaks, allPoints, points) : []
  const description = `${chart.title}: ${metrics.map((m) => m.label).join(", ")} over ${points.length} metingen, van ${
    labels.get(points[0].scan_id) ?? ""
  } tot ${lastLabel}. De exacte waarden staan in de tabel.`
  const footer =
    markers.length > 0 ? (
      <p className="text-xs text-muted-foreground">
        Nieuwe regelset vanaf {joinLabels(markers.map((m) => labels.get(m.x) ?? ""))} (
        {markers.map((m) => `v${m.brk.from} → v${m.brk.to}`).join(", ")}): controles die toen zijn toegevoegd, tellen als
        &lsquo;nieuwe controles&rsquo;.
      </p>
    ) : undefined
  const common = {
    data,
    series,
    formatValue,
    formatTick,
    yDomain: chart.yDomain,
    integerTicks: unit === "count",
    markers: markers.map(({ x, label }) => ({ x, label })),
    description,
  }

  return (
    <ChartFrame
      title={chart.title}
      description={chart.description}
      legend={series}
      legendShape={chart.kind === "line" ? "line" : "rect"}
      height={chart.kind === "line" ? LINE_HEIGHT : BAR_HEIGHT}
      loading={loading}
      empty={measured ? undefined : "Niet gemeten in deze periode."}
      footer={footer}
    >
      {chart.kind === "line" ? (
        <TrendLineChart {...common} invertY={chart.invertY} />
      ) : (
        <StackedBarChart {...common} stacked={chart.kind === "stacked-bar"} />
      )}
    </ChartFrame>
  )
}
