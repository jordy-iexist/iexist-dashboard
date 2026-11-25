import { ContentGapView } from "@/components/klanten/zoekwoorden/content-gap/ContentGapView"
import { fetchCustomerDetail } from "@/lib/customer-api"

export const metadata = {
  title: "Content gap",
}

type ContentGapPageProps = {
  params: Promise<{ customerId: string }>
}

/** Zoekwoorden › Content gap van één klant; de view haalt de gegevens zelf op (met polling). */
export default async function ContentGapPage({ params }: ContentGapPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <ContentGapView
      // Bij een andere klant begint de staat opnieuw.
      key={customer.id}
      customerId={customer.id}
      customerName={customer.name}
      domain={customer.domain}
    />
  )
}
