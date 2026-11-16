import Link from "next/link"
import { ArrowLeft, ExternalLink } from "lucide-react"

import { GoLiveWorkspace } from "@/components/livegang/GoLiveWorkspace"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Livegang",
}

type LivegangOpleveringKlantPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function LivegangOpleveringKlantPage({ params }: LivegangOpleveringKlantPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <Link
          href="/dashboard/livegang/oplevering"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Livegang
        </Link>
        <div className="space-y-0.5">
          <h1 className="text-2xl font-bold tracking-tight text-primary sm:text-3xl">{customer.name}</h1>
          <a
            href={customer.base_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            {customer.domain}
            <ExternalLink className="size-3.5" />
          </a>
        </div>
      </header>
      <GoLiveWorkspace customerId={customer.id} />
    </div>
  )
}
