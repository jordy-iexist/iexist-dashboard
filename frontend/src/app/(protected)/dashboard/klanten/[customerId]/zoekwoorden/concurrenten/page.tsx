import { ConcurrentenView } from "@/components/klanten/zoekwoorden/ConcurrentenView"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Concurrenten",
}

type ConcurrentenPageProps = {
  params: Promise<{ customerId: string }>
}

/** Zoekwoorden › Concurrenten van één klant; het overzicht zelf haalt de view op (met polling). */
export default async function ConcurrentenPage({ params }: ConcurrentenPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <ConcurrentenView
      // Bij een andere klant begint de staat opnieuw.
      key={customer.id}
      customerId={customer.id}
      customerName={customer.name}
      domain={customer.domain}
    />
  )
}
