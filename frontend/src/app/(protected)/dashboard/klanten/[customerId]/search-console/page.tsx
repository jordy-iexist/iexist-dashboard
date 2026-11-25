import { Suspense } from "react"

import { formatShortDate } from "@/components/klanten/analyses/result-parts"
import { ExportOpportunitiesButton } from "@/components/klanten/search-console/ExportOpportunitiesButton"
import { PeriodPicker } from "@/components/klanten/search-console/PeriodPicker"
import { SearchConsoleInsights } from "@/components/klanten/search-console/SearchConsoleInsights"
import { SearchConsoleInsightsSkeleton } from "@/components/klanten/search-console/SearchConsoleInsightsSkeleton"
import { fetchCustomerDetail, fetchCustomerSearchConsoleInsights } from "@/lib/customer-api"
import { parsePeriodDays, PERIOD_PARAM, type PeriodDays } from "@/lib/search-console-insights"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Search Console",
}

type SearchConsolePageProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

/** Property en datums onder de kop; alleen als Search Console cijfers leverde. */
async function PropertyLine({ customerId, days }: { customerId: string; days: PeriodDays }) {
  const insights = await fetchCustomerSearchConsoleInsights(customerId, days)
  if (insights.state !== "ok" || !insights.property) return null
  const start = formatShortDate(insights.period?.start)
  const end = formatShortDate(insights.period?.end)
  const source =
    insights.property_source === "manual"
      ? " (handmatig gekozen)"
      : insights.property_source === "auto"
        ? " (automatisch gevonden)"
        : ""
  return (
    <p className="text-xs break-all text-muted-foreground">
      Property <span className="font-mono">{insights.property}</span>
      {source}
      {start && end && ` · ${start} t/m ${end}`}
    </p>
  )
}

/** Exportknop; uitgeschakeld zolang er (nog) geen kansen zijn. */
async function ExportButton({
  customerId,
  days,
  domain,
}: {
  customerId: string
  days: PeriodDays
  domain: string
}) {
  const insights = await fetchCustomerSearchConsoleInsights(customerId, days)
  const rows =
    insights.state === "ok" && insights.opportunities.state === "ok"
      ? insights.opportunities.rows
      : []
  return (
    <ExportOpportunitiesButton
      rows={rows}
      domain={domain}
      endDate={insights.period?.end ?? null}
      days={days}
    />
  )
}

export default async function SearchConsolePage({ params, searchParams }: SearchConsolePageProps) {
  const [{ customerId }, query] = await Promise.all([params, searchParams])
  const days = parsePeriodDays(query[PERIOD_PARAM])
  const customer = await fetchCustomerDetail(customerId)
  // Bij een andere klant of periode opnieuw het skelet tonen in plaats van de oude cijfers.
  const contentKey = `${customer.id}|${days}`

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Search Console
          </p>
          <h1 className="text-2xl font-bold tracking-tight break-words sm:text-3xl">
            {customer.name}
          </h1>
          <p className="text-sm text-muted-foreground">
            <a
              href={customer.base_url}
              target="_blank"
              rel="noreferrer noopener"
              className="break-all underline-offset-4 hover:text-foreground hover:underline"
            >
              {customer.domain}
            </a>
            {` · laatste ${days} dagen vs. vorige periode · bron: Google Search Console`}
          </p>
          <Suspense key={contentKey} fallback={null}>
            <PropertyLine customerId={customer.id} days={days} />
          </Suspense>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PeriodPicker customerId={customer.id} days={days} />
          <Suspense
            key={contentKey}
            fallback={
              <ExportOpportunitiesButton rows={[]} domain={customer.domain} endDate={null} days={days} />
            }
          >
            <ExportButton customerId={customer.id} days={days} domain={customer.domain} />
          </Suspense>
        </div>
      </header>

      <Suspense key={contentKey} fallback={<SearchConsoleInsightsSkeleton />}>
        <SearchConsoleInsights customerId={customer.id} days={days} />
      </Suspense>
    </div>
  )
}
