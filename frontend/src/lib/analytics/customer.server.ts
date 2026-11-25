import { redirect } from "next/navigation"

import { readActiveCustomerCookie } from "@/lib/active-customer.server"
import { parseAnalyticsFilters } from "@/lib/analytics/api"
import { fetchCustomerList } from "@/lib/customer-api"
import { toQueryString, type PageSearchParams } from "@/lib/search-params"

/**
 * Klant van een Analytics-pagina (`path`). Staat `klant` niet in het adres, dan
 * door naar `path` voor de laatst gekozen klant (cookie), als die nog bestaat;
 * de overige parameters blijven staan. `null`: geen klant bekend.
 */
export async function resolveAnalyticsCustomer(params: PageSearchParams, path: string): Promise<string | null> {
  const { customerId } = parseAnalyticsFilters(params)
  if (customerId) return customerId

  const activeCustomerId = await readActiveCustomerCookie()
  if (activeCustomerId) {
    const customers = await fetchCustomerList()
    if (customers.some((customer) => customer.id === activeCustomerId)) {
      redirect(`${path}${toQueryString({ ...params, klant: activeCustomerId })}`)
    }
  }
  return null
}
