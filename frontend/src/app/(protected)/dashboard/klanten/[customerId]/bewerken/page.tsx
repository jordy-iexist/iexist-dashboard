import { KlantHero } from "@/components/klanten/KlantHero"
import { KlantProfielForm } from "@/components/klanten/KlantProfielForm"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Klant bewerken",
}

type KlantBewerkenPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function KlantBewerkenPage({
  params,
}: KlantBewerkenPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8">
      <KlantHero
        backHref={`/dashboard/klanten/${customer.id}`}
        backLabel="Terug naar klant"
        eyebrow={customer.name}
        title="Klant bewerken"
      />

      <KlantProfielForm customer={customer} />
    </div>
  )
}
