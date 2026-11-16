"use client"

import Link from "next/link"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { useRequest } from "@/components/analytics/compare/use-request"
import { ErrorNote } from "@/components/analytics/states"
import { CompactStat, StatGrid } from "@/components/livegang/shared"
import { fetchBenchmark, type BenchmarkResponse } from "@/lib/analytics/api"
import { formatMetricValue } from "@/lib/analytics/format"

/** Kerncijfers waarvan de overzichtspagina de mediaan over alle klanten toont. */
const MEDIAN_TILES = [
  { key: "ai_score", label: "Mediaan AI-score" },
  { key: "issues_comparable", label: "Mediaan actiepunten" },
  { key: "domain_rating", label: "Mediaan Domain Rating" },
  { key: "prt_visibility", label: "Mediaan AI-zichtbaarheid" },
] as const

/** KPI-tegels uit de benchmark: hoeveel klanten een scan hebben en de mediaan van vier kerncijfers. */
export function OverviewKpis() {
  const { data, error } = useRequest<BenchmarkResponse>("benchmark", (signal) => fetchBenchmark({ signal }))

  if (error) return <ErrorNote>{error}</ErrorNote>

  const units = new Map(data?.metrics.map((m) => [m.key, m.unit]))
  const withScan = data ? data.rows.filter((row) => row.scan).length : null

  return (
    <div className="space-y-2" aria-busy={!data}>
      <StatGrid className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        <CompactStat
          label="Klanten met een scan"
          value={withScan ?? "…"}
          hint={data ? `van ${data.rows.length} ${data.rows.length === 1 ? "klant" : "klanten"} in de livegang` : undefined}
        />
        {MEDIAN_TILES.map((tile) => {
          const summary = data?.summary[tile.key]
          const unit = units.get(tile.key) ?? "count"
          return (
            <CompactStat
              key={tile.key}
              label={tile.label}
              value={!data ? "…" : formatMetricValue(summary?.median ?? null, unit)}
              hint={
                !data
                  ? undefined
                  : summary && summary.n > 0
                    ? `n = ${summary.n} ${summary.n === 1 ? "klant" : "klanten"}`
                    : "Bij geen enkele klant gemeten"
              }
            />
          )
        })}
      </StatGrid>
      <p className="text-right text-sm">
        <Link
          href={`${ANALYTICS_BASE_URL}/vergelijken?modus=klanten`}
          className="font-medium text-primary hover:underline"
        >
          Alle klanten vergelijken →
        </Link>
      </p>
    </div>
  )
}
