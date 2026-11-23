import { AnalysisResult } from "@/components/klanten/analyses/AnalysisResult"
import { KEYWORD_PARAM } from "@/lib/competitor-analysis"
import { fetchCustomerDetail } from "@/lib/customer-api"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Concurrentieanalyse",
}

type AnalysisPageProps = {
  params: Promise<{ customerId: string; analysisId: string }>
  searchParams: Promise<PageSearchParams>
}

// `?zoekwoord=<keywordId>` opent het resultaat direct op dat zoekwoord.
export default async function AnalysisPage({ params, searchParams }: AnalysisPageProps) {
  const [{ customerId, analysisId }, query] = await Promise.all([params, searchParams])
  const customer = await fetchCustomerDetail(customerId)
  const keywordParam = query[KEYWORD_PARAM]
  const keywordId = (Array.isArray(keywordParam) ? keywordParam[0] : keywordParam)?.trim() || null

  return (
    <AnalysisResult
      customerId={customer.id}
      customerName={customer.name}
      customerDomain={customer.domain}
      customerBaseUrl={customer.base_url}
      analysisId={analysisId}
      initialKeywordId={keywordId}
    />
  )
}
