import { ContentBriefView } from "@/components/klanten/analyses/brief/ContentBriefView"
import { KEYWORD_PARAM } from "@/lib/competitor-analysis"
import { fetchCustomerDetail } from "@/lib/customer-api"
import type { PageSearchParams } from "@/lib/search-params"

export const metadata = {
  title: "Content brief",
}

type BriefPageProps = {
  params: Promise<{ customerId: string; analysisId: string }>
  searchParams: Promise<PageSearchParams>
}

// `?zoekwoord=<keywordId>` kiest het zoekwoord uit de analyse waar de brief bij hoort.
export default async function BriefPage({ params, searchParams }: BriefPageProps) {
  const [{ customerId, analysisId }, query] = await Promise.all([params, searchParams])
  const customer = await fetchCustomerDetail(customerId)
  const keywordParam = query[KEYWORD_PARAM]
  const keywordId = (Array.isArray(keywordParam) ? keywordParam[0] : keywordParam)?.trim() || null

  return (
    <ContentBriefView
      customerId={customer.id}
      customerName={customer.name}
      analysisId={analysisId}
      keywordId={keywordId}
    />
  )
}
