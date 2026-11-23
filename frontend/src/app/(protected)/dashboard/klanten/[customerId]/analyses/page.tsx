import Link from "next/link"
import { Plus } from "lucide-react"

import { AnalysesList } from "@/components/klanten/analyses/AnalysesList"
import { Button } from "@/components/ui/button"
import { newAnalysisHref } from "@/lib/competitor-analysis"
import { fetchRecentAnalyses } from "@/lib/competitor-analysis.server"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Concurrentieanalyse",
}

/** Zoveel analyses toont de lijst (nieuwste eerst). */
const LIST_LIMIT = 50

type AnalysesPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function AnalysesPage({ params }: AnalysesPageProps) {
  const { customerId } = await params
  const [customer, analyses] = await Promise.all([
    fetchCustomerDetail(customerId),
    fetchRecentAnalyses(customerId, LIST_LIMIT),
  ])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Concurrentieanalyse
          </p>
          <h1 className="text-2xl font-bold tracking-tight break-words sm:text-3xl">
            {customer.name}
          </h1>
          <a
            href={customer.base_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-block text-sm break-all text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            {customer.domain}
          </a>
        </div>
        {!analyses.failed && analyses.items.length > 0 && (
          <Button asChild className="font-semibold">
            <Link href={newAnalysisHref(customer.id)}>
              <Plus />
              Nieuwe analyse
            </Link>
          </Button>
        )}
      </header>

      <AnalysesList
        customerId={customer.id}
        initialItems={analyses.items}
        initialFailed={analyses.failed}
        limit={LIST_LIMIT}
      />
    </div>
  )
}
