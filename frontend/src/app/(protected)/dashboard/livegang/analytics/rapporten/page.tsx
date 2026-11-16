import { ReportList } from "@/components/analytics/ReportList"
import { parseAnalyticsFilters } from "@/lib/analytics/api"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Rapporten · Analytics",
}

export default async function RapportenPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const { customerId } = parseAnalyticsFilters(await searchParams)
  return <ReportList customerId={customerId} />
}
