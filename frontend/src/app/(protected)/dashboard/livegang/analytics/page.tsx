import { AnalyticsOverview } from "@/components/analytics/AnalyticsOverview"
import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { NoCustomerState } from "@/components/analytics/states"
import { resolveAnalyticsCustomer } from "@/lib/analytics/customer.server"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Overzicht · Analytics",
}

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const customerId = await resolveAnalyticsCustomer(await searchParams, ANALYTICS_BASE_URL)
  if (!customerId) return <NoCustomerState />
  return <AnalyticsOverview customerId={customerId} />
}
