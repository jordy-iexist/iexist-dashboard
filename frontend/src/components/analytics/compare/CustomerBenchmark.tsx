"use client"

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { useId, useState } from "react"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { ChartFrame, RankBarChart, rankBarChartHeight, type RankBarItem } from "@/components/analytics/charts"
import { useRequest } from "@/components/analytics/compare/use-request"
import { EmptyState, ErrorNote } from "@/components/analytics/states"
import { Pill } from "@/components/livegang/shared"
import { useIsMobile } from "@/hooks/use-mobile"
import {
  CHECKLIST_GROUP,
  fetchBenchmark,
  type BenchmarkResponse,
  type BenchmarkRow,
  type MetricDef,
  type MetricSummary,
} from "@/lib/analytics/api"
import {
  BENCHMARK_CORE_METRICS,
  DEFAULT_BENCHMARK_METRIC,
  groupMetrics,
  isStale,
  STALE_AFTER_DAYS,
} from "@/lib/analytics/compare"
import { formatAxisTick, formatDate, formatMetricValue, unitDescription } from "@/lib/analytics/format"
import { joinLabels, metricIndex } from "@/lib/analytics/trend"
import { cn } from "@/lib/utils"

const selectClass =
  "h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"

/** Benchmark plus het moment van ophalen (voor "ouder dan 180 dagen", buiten de render). */
type Loaded = { benchmark: BenchmarkResponse; now: number }

type SortKey = "name" | "scan" | string
type Sort = { key: SortKey; dir: "asc" | "desc" }

export type CustomerBenchmarkProps = {
  metricKey: string
  onMetricChange: (metricKey: string) => void
  /** Klik op een klantnaam: naar de modus Trend voor die klant. */
  onOpenTrend: (customerId: string) => void
}

/** Modus Klanten onderling: alle klanten op één metric, gesorteerd van beste naar slechtste. */
export function CustomerBenchmark({ metricKey, onMetricChange, onOpenTrend }: CustomerBenchmarkProps) {
  const { data, error } = useRequest<Loaded>("benchmark", (signal) =>
    fetchBenchmark({ signal }).then((benchmark) => ({ benchmark, now: Date.now() }))
  )
  // Expliciete sortering van de tabel; `null` = de gekozen metric, beste eerst.
  const [sort, setSort] = useState<Sort | null>(null)

  if (error) return <ErrorNote>{error}</ErrorNote>
  if (!data) return <p className="text-sm text-muted-foreground">Klanten laden…</p>

  const { benchmark, now } = data
  const index = metricIndex(benchmark.metrics)
  const metric = index.get(metricKey) ?? index.get(DEFAULT_BENCHMARK_METRIC) ?? benchmark.metrics[0]
  if (!metric) return <EmptyState>Er zijn nog geen cijfers om klanten op te vergelijken.</EmptyState>
  if (benchmark.rows.length === 0) {
    return <EmptyState>Er zijn nog geen klanten met een voltooide scan of checklist.</EmptyState>
  }

  function changeMetric(key: string) {
    setSort(null)
    onMetricChange(key)
  }

  return (
    <div className="space-y-6">
      <MetricSelect metrics={benchmark.metrics} value={metric.key} onChange={changeMetric} />
      <BenchmarkChart metric={metric} rows={benchmark.rows} summary={benchmark.summary[metric.key]} now={now} />
      <BenchmarkTable
        metric={metric}
        index={index}
        rows={benchmark.rows}
        sort={sort ?? { key: metric.key, dir: bestFirst(metric) }}
        onSort={setSort}
        now={now}
        onOpenTrend={onOpenTrend}
      />
    </div>
  )
}

function bestFirst(metric: MetricDef): "asc" | "desc" {
  return metric.higher_is_better === false ? "asc" : "desc"
}

function MetricSelect({ metrics, value, onChange }: { metrics: MetricDef[]; value: string; onChange: (key: string) => void }) {
  const id = useId()
  return (
    <div className="w-full space-y-1 sm:w-80">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        Cijfer
      </label>
      <select id={id} className={selectClass} value={value} onChange={(e) => onChange(e.target.value)}>
        {groupMetrics(metrics).map((group) => (
          <optgroup
            key={group.group}
            label={group.group === CHECKLIST_GROUP ? `${group.label} (huidige stand)` : group.label}
          >
            {group.metrics.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  )
}

function BenchmarkChart({
  metric,
  rows,
  summary,
  now,
}: {
  metric: MetricDef
  rows: BenchmarkRow[]
  summary: MetricSummary | undefined
  now: number
}) {
  const isMobile = useIsMobile()
  const isChecklist = metric.group === CHECKLIST_GROUP
  const measured = rows.filter((row) => row.values[metric.key] != null)
  const missing = rows.filter((row) => row.values[metric.key] == null)
  const items: RankBarItem[] = measured.map((row) => ({
    key: row.customer.id,
    label: row.customer.name,
    value: row.values[metric.key] ?? null,
    muted: !isChecklist && isStale(row.scan, now),
  }))
  const anyMuted = items.some((item) => item.muted)
  const format = (value: number) => formatMetricValue(value, metric.unit)
  const median = summary?.median ?? null
  const n = summary?.n ?? measured.length
  const direction =
    metric.higher_is_better === false ? "Lager is beter; beste bovenaan." : metric.higher_is_better ? "Hoger is beter; beste bovenaan." : "Van hoog naar laag."

  const description = isChecklist
    ? `Huidige stand van de checklist per klant, niet gekoppeld aan een scandatum. ${direction}`
    : `Laatste nulmeting of kwartaalscan per klant. ${direction}`

  const footer = (
    <div className="space-y-1 text-xs text-muted-foreground">
      {n === 1 && <p>Maar één klant heeft hier een waarde; een mediaan volgt vanaf twee klanten.</p>}
      {anyMuted && (
        <p className="flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-[2px] bg-[var(--chart-1)] opacity-40" />
          Lichter: laatste scan is ouder dan {STALE_AFTER_DAYS} dagen.
        </p>
      )}
      {missing.length > 0 && (
        <p>
          <span className="font-medium text-foreground">Niet gemeten</span>: {joinLabels(missing.map((r) => r.customer.name))}
          {!isChecklist && missing.some((r) => !r.scan) ? " (zonder voltooide nulmeting of kwartaalscan)" : ""}.
        </p>
      )}
    </div>
  )

  return (
    <ChartFrame
      title={metric.label}
      description={description}
      height={rankBarChartHeight(Math.max(items.length, 1)) + (median != null && n >= 2 ? 16 : 0)}
      empty={items.length === 0 ? "Bij geen enkele klant gemeten." : undefined}
      footer={footer}
    >
      <RankBarChart
        items={items}
        formatValue={format}
        formatTick={(value) => formatAxisTick(value, metric.unit)}
        sort={bestFirst(metric)}
        reference={median != null && n >= 2 ? { value: median, label: `Mediaan ${format(median)} (n = ${n})` } : undefined}
        domain={metric.unit === "percent" || metric.unit === "score" ? [0, 100] : undefined}
        seriesLabel={metric.label}
        labelWidth={isMobile ? 96 : 140}
        description={`${metric.label} per klant (${unitDescription(metric)}): ${items
          .map((item) => `${item.label} ${item.value == null ? "niet gemeten" : format(item.value)}`)
          .join("; ")}.`}
      />
    </ChartFrame>
  )
}

function BenchmarkTable({
  metric,
  index,
  rows,
  sort,
  onSort,
  now,
  onOpenTrend,
}: {
  metric: MetricDef
  index: Map<string, MetricDef>
  rows: BenchmarkRow[]
  sort: Sort
  onSort: (sort: Sort) => void
  now: number
  onOpenTrend: (customerId: string) => void
}) {
  const columns = [metric, ...BENCHMARK_CORE_METRICS.filter((key) => key !== metric.key).map((key) => index.get(key))].filter(
    (m): m is MetricDef => !!m
  )
  const sorted = sortRows(rows, sort)

  function toggle(key: SortKey, defaultDir: "asc" | "desc") {
    onSort(sort.key === key ? { key, dir: sort.dir === "asc" ? "desc" : "asc" } : { key, dir: defaultDir })
  }

  return (
    <div className="relative overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <caption className="sr-only">Klanten met hun laatste scan, {metric.label} en kerncijfers</caption>
        <thead className="bg-muted text-xs text-muted-foreground">
          <tr>
            <SortHeader label="Klant" sortKey="name" sort={sort} onToggle={() => toggle("name", "asc")} align="left" sticky />
            <SortHeader label="Scan" sortKey="scan" sort={sort} onToggle={() => toggle("scan", "desc")} align="left" />
            {columns.map((m) => (
              <SortHeader
                key={m.key}
                label={m.label}
                sortKey={m.key}
                sort={sort}
                onToggle={() => toggle(m.key, bestFirst(m))}
                align="right"
                emphasis={m.key === metric.key}
              />
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {sorted.map((row) => {
            const href = `${ANALYTICS_BASE_URL}/vergelijken?modus=trend&klant=${encodeURIComponent(row.customer.id)}`
            const stale = isStale(row.scan, now)
            return (
              <tr key={row.customer.id}>
                <th scope="row" className="sticky left-0 z-[1] min-w-36 bg-card px-3 py-2 text-left font-normal">
                  <a
                    href={href}
                    className="font-medium text-primary hover:underline"
                    title={`Trend van ${row.customer.name}`}
                    onClick={(e) => {
                      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
                      e.preventDefault()
                      onOpenTrend(row.customer.id)
                    }}
                  >
                    {row.customer.name}
                  </a>
                  <span className="block text-xs text-muted-foreground">{row.customer.domain}</span>
                </th>
                <td className="px-3 py-2 whitespace-nowrap">
                  {row.scan ? (
                    <>
                      <span className="block">{row.scan.label}</span>
                      <span className={cn("flex items-center gap-1.5 text-xs text-muted-foreground")}>
                        {formatDate(row.scan.date)}
                        {stale && <Pill tone="amber">ouder dan {STALE_AFTER_DAYS} dagen</Pill>}
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">Geen nulmeting of kwartaalscan</span>
                  )}
                </td>
                {columns.map((m) => {
                  const value = row.values[m.key] ?? null
                  return (
                    <td
                      key={m.key}
                      className={cn(
                        "px-3 py-2 text-right tabular-nums whitespace-nowrap",
                        value == null && "text-muted-foreground",
                        m.key === metric.key && "font-medium"
                      )}
                    >
                      {value == null ? <span title="Niet gemeten">–</span> : formatMetricValue(value, m.unit)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SortHeader({
  label,
  sortKey,
  sort,
  onToggle,
  align,
  sticky = false,
  emphasis = false,
}: {
  label: string
  sortKey: SortKey
  sort: Sort
  onToggle: () => void
  align: "left" | "right"
  sticky?: boolean
  emphasis?: boolean
}) {
  const active = sort.key === sortKey
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        "px-3 py-2 font-medium align-bottom",
        align === "right" ? "min-w-24 text-right" : "text-left",
        sticky && "sticky left-0 z-[1] bg-muted",
        emphasis && "text-foreground"
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "inline-flex items-center gap-1 hover:text-foreground",
          align === "right" && "flex-row-reverse text-right"
        )}
      >
        <span className="min-w-0">{label}</span>
        <Icon className={cn("size-3 shrink-0", !active && "opacity-50")} aria-hidden />
      </button>
    </th>
  )
}

/** Sorteert op naam, scandatum of een metric; ontbrekende waarden altijd onderaan. */
function sortRows(rows: BenchmarkRow[], sort: Sort): BenchmarkRow[] {
  const factor = sort.dir === "asc" ? 1 : -1
  const valueOf = (row: BenchmarkRow): number | string | null => {
    if (sort.key === "name") return row.customer.name.toLocaleLowerCase("nl")
    if (sort.key === "scan") return row.scan ? new Date(row.scan.date).getTime() : null
    return row.values[sort.key] ?? null
  }
  return [...rows].sort((x, y) => {
    const a = valueOf(x)
    const b = valueOf(y)
    if (a == null && b == null) return x.customer.name.localeCompare(y.customer.name, "nl")
    if (a == null) return 1
    if (b == null) return -1
    if (typeof a === "string" || typeof b === "string") return String(a).localeCompare(String(b), "nl") * factor
    return a === b ? x.customer.name.localeCompare(y.customer.name, "nl") : (a - b) * factor
  })
}
