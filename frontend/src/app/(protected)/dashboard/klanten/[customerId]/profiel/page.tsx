import { KlantProfiel } from "@/components/klanten/profiel/KlantProfiel"
import { KoppelingenCard } from "@/components/klanten/profiel/KoppelingenCard"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Klantprofiel",
}

type KlantProfielPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function KlantProfielPage({ params }: KlantProfielPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  // `key`: bij het wisselen van klant begint het formulier opnieuw met de gegevens van de
  // nieuwe klant. De koppelingen laden los (Suspense in de kaart), de rest staat er direct.
  return (
    <KlantProfiel
      key={customer.id}
      customer={customer}
      connections={<KoppelingenCard customer={customer} />}
    />
  )
}
