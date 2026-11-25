import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { CompareView } from "@/components/analytics/compare/CompareView"
import { NoCustomerState } from "@/components/analytics/states"
import { resolveAnalyticsCustomer } from "@/lib/analytics/customer.server"
import { parseCompareParams } from "@/lib/analytics/compare"
import { toQueryString, type PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Vergelijken · Analytics",
}

export default async function VergelijkenPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const params = await searchParams
  const customerId = await resolveAnalyticsCustomer(params, `${ANALYTICS_BASE_URL}/vergelijken`)
  if (!customerId) return <NoCustomerState />
  // Nieuwe navigatie (bijv. de tab Vergelijken aanklikken of een andere klant in de sidebar) =
  // nieuwe beginstand. Keuzes op de pagina zelf schrijven de URL met replaceState en laden de
  // pagina niet opnieuw.
  return <CompareView key={toQueryString(params)} customerId={customerId} initialState={parseCompareParams(params)} />
}
