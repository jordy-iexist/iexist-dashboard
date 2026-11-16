import { CompareView } from "@/components/analytics/compare/CompareView"
import { parseCompareParams } from "@/lib/analytics/compare"
import { toQueryString, type PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Vergelijken · Analytics",
}

export default async function VergelijkenPage({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  const params = await searchParams
  // Nieuwe navigatie (bijv. de tab Vergelijken aanklikken) = nieuwe beginstand. Keuzes op de
  // pagina zelf schrijven de URL met replaceState en laden de pagina niet opnieuw.
  return <CompareView key={toQueryString(params)} initialState={parseCompareParams(params)} />
}
