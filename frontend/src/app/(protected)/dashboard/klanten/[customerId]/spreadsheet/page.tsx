import Link from "next/link"
import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { KlantSpreadsheet } from "@/components/klanten/KlantSpreadsheet"
import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import { type CustomerWebsiteDetail } from "@/lib/customer-types"

export const metadata = {
  title: "Klant spreadsheet",
}

type KlantSpreadsheetPageProps = {
  params: Promise<{ customerId: string }>
}

export default async function KlantSpreadsheetPage({
  params,
}: KlantSpreadsheetPageProps) {
  noStore()

  const { customerId } = await params
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let customer: CustomerWebsiteDetail | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/customers/${encodeURIComponent(customerId)}`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      notFound()
    }

    customer = (await response.json().catch(() => null)) as CustomerWebsiteDetail | null
  } catch {
    notFound()
  }

  if (!customer?.id) {
    notFound()
  }

  return (
    <div className="-m-4 space-y-6 px-4 py-4 lg:-m-6 lg:px-6">
      <div className="space-y-2">
        <Link
          href={`/dashboard/klanten/${customer.id}`}
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar klant
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">
          Spreadsheet — {customer.name}
        </h1>
        <p className="text-muted-foreground">
          Elke blog van deze klant staat automatisch als rij. Vink een blog aan
          als geplaatst, of voeg zelf kolommen toe.
        </p>
      </div>

      <KlantSpreadsheet customerId={customer.id} />
    </div>
  )
}
