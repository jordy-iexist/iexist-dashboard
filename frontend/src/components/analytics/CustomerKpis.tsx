"use client"

import Link from "next/link"

import { useRequest } from "@/components/analytics/compare/use-request"
import { KpiTile } from "@/components/analytics/KpiTile"
import { EmptyState, ErrorNote } from "@/components/analytics/states"
import { StatGrid } from "@/components/livegang/shared"
import { fetchTrend, type MetricDef, type TrendResponse } from "@/lib/analytics/api"
import { formatDate } from "@/lib/analytics/format"
import { metricIndex, pointLabels, selectPoints } from "@/lib/analytics/trend"

/** Kerncijfers op de overzichtspagina: AI-score, actiepunten, Domain Rating en AI-zichtbaarheid. */
const CORE_METRICS = ["ai_score", "issues_comparable", "domain_rating", "prt_visibility"]

/** Vier kerncijfers van één klant: de laatste meting, met het verschil t.o.v. de meting ervoor. */
export function CustomerKpis({ customerId }: { customerId: string }) {
  const { data, error } = useRequest<TrendResponse>(customerId, (signal) => fetchTrend(customerId, {}, { signal }))

  if (error) return <ErrorNote>{error}</ErrorNote>
  if (!data) return <p className="text-sm text-muted-foreground">Kerncijfers laden…</p>

  const { customer } = data
  const points = selectPoints(data.points, { phases: [1, 4], allScans: false })
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

  const index = metricIndex(data.metrics)
  // Een key die de API (nog) niet kent, valt weg.
  const metrics = CORE_METRICS.map((key) => index.get(key)).filter((m): m is MetricDef => !!m)
  const labels = pointLabels(points)
  const first = points[0]
  const last = points[points.length - 1]
  const previous = points.length > 1 ? points[points.length - 2] : null

  return (
    <div className="space-y-2">
      {metrics.length > 0 && (
        <StatGrid className="grid-cols-2 lg:grid-cols-4">
          {metrics.map((metric) => (
            <KpiTile key={metric.key} metric={metric} last={last} previous={previous} labels={labels} />
          ))}
        </StatGrid>
      )}
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">{customer.name}</span> · {customer.domain} · {points.length}{" "}
        {points.length === 1 ? "meting" : "metingen"},{" "}
        {points.length === 1 ? formatDate(first.date) : `${formatDate(first.date)} t/m ${formatDate(last.date)}`}
      </p>
    </div>
  )
}
