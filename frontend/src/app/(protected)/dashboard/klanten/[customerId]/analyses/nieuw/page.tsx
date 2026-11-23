import { AnalysisWizard } from "@/components/klanten/analyses/AnalysisWizard"
import { KEYWORD_PARAM, keywordsFromParam } from "@/lib/competitor-analysis"
import { fetchCustomerDetail } from "@/lib/customer-api"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Nieuwe analyse",
}

type NewAnalysisPageProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

// `?zoekwoord=a&zoekwoord=b` vult de wizard met deze zoekwoorden (bijv. vanuit de Quick wins).
export default async function NewAnalysisPage({ params, searchParams }: NewAnalysisPageProps) {
  const [{ customerId }, query] = await Promise.all([params, searchParams])
  const customer = await fetchCustomerDetail(customerId)

  return (
    <AnalysisWizard
      customerId={customer.id}
      customerName={customer.name}
      customerDomain={customer.domain}
      customerBaseUrl={customer.base_url}
      initialKeywords={keywordsFromParam(query[KEYWORD_PARAM])}
    />
  )
}
