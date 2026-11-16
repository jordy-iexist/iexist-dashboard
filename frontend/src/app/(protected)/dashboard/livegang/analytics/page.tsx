import { AnalyticsOverview } from "@/components/analytics/AnalyticsOverview"
import { parseAnalyticsFilters } from "@/lib/analytics/api"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Overzicht · Analytics",
}

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const { customerId } = parseAnalyticsFilters(await searchParams)
  return <AnalyticsOverview customerId={customerId} />
}
