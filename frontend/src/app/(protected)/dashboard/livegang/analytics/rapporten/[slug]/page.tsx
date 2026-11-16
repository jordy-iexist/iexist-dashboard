import { notFound } from "next/navigation"

import { ReportView } from "@/components/analytics/ReportView"
import { parseAnalyticsFilters } from "@/lib/analytics/api"
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
  const initialFilters = parseAnalyticsFilters(await searchParams)
  return <ReportView slug={report.slug} initialFilters={initialFilters} />
}
