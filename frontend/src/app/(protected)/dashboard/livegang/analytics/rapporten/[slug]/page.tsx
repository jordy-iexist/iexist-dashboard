import { notFound } from "next/navigation"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { ReportView } from "@/components/analytics/ReportView"
import { NoCustomerState } from "@/components/analytics/states"
import { parseAnalyticsFilters } from "@/lib/analytics/api"
import { resolveAnalyticsCustomer } from "@/lib/analytics/customer.server"
import { getReport } from "@/lib/analytics/reports"
import type { PageSearchParams } from "@/lib/search-params"

type RapportPageProps = {
  params: Promise<{ slug: string }>
  searchParams: Promise<PageSearchParams>
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const report = getReport((await params).slug)
  return { title: report ? `${report.title} · Analytics` : "Analytics" }
}

export default async function RapportPage({ params, searchParams }: RapportPageProps) {
  const { slug } = await params
  const report = getReport(slug)
  if (!report) notFound()
  const query = await searchParams
  const customerId = await resolveAnalyticsCustomer(query, `${ANALYTICS_BASE_URL}/rapporten/${report.slug}`)
  if (!customerId) return <NoCustomerState />
  // key: een andere klant (via de sidebar) begint met een schone rapportstand.
  return <ReportView key={customerId} slug={report.slug} initialFilters={parseAnalyticsFilters(query)} />
}
