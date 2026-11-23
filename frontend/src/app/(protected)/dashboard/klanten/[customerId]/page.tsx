import { Suspense } from "react"

import { CustomerPerformance } from "@/components/klanten/dashboard/CustomerPerformance"
import { CustomerPerformanceSkeleton } from "@/components/klanten/dashboard/CustomerPerformanceSkeleton"
import { RefreshQuickWinsButton } from "@/components/klanten/dashboard/RefreshQuickWinsButton"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Klant",
}

type KlantDetailPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function KlantDetailPage({ params }: KlantDetailPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          {customer.category_name && (
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {customer.category_name}
            </p>
          )}
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
        <RefreshQuickWinsButton customerId={customer.id} />
      </header>

      <Suspense key={customer.id} fallback={<CustomerPerformanceSkeleton />}>
        <div className="space-y-6">
          <CustomerPerformance customerId={customer.id} customerName={customer.name} />
        </div>
      </Suspense>
    </div>
  )
}
