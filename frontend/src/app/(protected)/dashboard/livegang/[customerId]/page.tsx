import { KlantHero } from "@/components/klanten/KlantHero"
import { LaunchScanWorkspace } from "@/components/livegang/LaunchScanWorkspace"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Livegang checklist",
}

type LivegangKlantPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function LivegangKlantPage({ params }: LivegangKlantPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <div className="space-y-8">
      <KlantHero
        backHref="/dashboard/livegang"
        backLabel="Terug naar livegang checklist"
        eyebrow="Livegang checklist"
        title={customer.name}
      >
        <a
          href={customer.base_url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-block text-lg text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {customer.domain}
        </a>
      </KlantHero>
      <LaunchScanWorkspace customerId={customer.id} />
    </div>
  )
}
