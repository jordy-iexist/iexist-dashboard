import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { ReportList } from "@/components/analytics/ReportList"
import { NoCustomerState } from "@/components/analytics/states"
import { resolveAnalyticsCustomer } from "@/lib/analytics/customer.server"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Rapporten · Analytics",
}

export default async function RapportenPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const customerId = await resolveAnalyticsCustomer(await searchParams, `${ANALYTICS_BASE_URL}/rapporten`)
  if (!customerId) return <NoCustomerState />
  return <ReportList customerId={customerId} />
}
