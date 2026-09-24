import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import { type CustomerWebsiteDetail } from "@/lib/customer-types"

export async function fetchCustomerDetail(
  customerId: string
): Promise<CustomerWebsiteDetail> {
  noStore()

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

  return customer
}
