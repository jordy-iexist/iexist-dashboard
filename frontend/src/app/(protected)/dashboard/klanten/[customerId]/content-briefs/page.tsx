import { ContentBriefsList } from "@/components/klanten/analyses/brief/ContentBriefsList"
import { fetchRecentBriefs } from "@/lib/content-brief.server"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Content briefs",
}

/** Zoveel content briefs toont de lijst (laatst bijgewerkte eerst). */
const LIST_LIMIT = 50

type ContentBriefsPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function ContentBriefsPage({ params }: ContentBriefsPageProps) {
  const { customerId } = await params
  const [customer, briefs] = await Promise.all([
    fetchCustomerDetail(customerId),
    fetchRecentBriefs(customerId, LIST_LIMIT),
  ])

  return (
    <div className="space-y-6">
      <header className="min-w-0 space-y-1">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Content briefs
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
      </header>

      <ContentBriefsList
        customerId={customer.id}
        initialItems={briefs.items}
        initialFailed={briefs.failed}
        limit={LIST_LIMIT}
      />
    </div>
  )
}
