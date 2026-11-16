import { redirect } from "next/navigation"

import { toQueryString, type PageSearchParams } from "@/lib/search-params"

type PrintRedirectProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

/** Oud adres van de printversie: doorsturen met behoud van `fase` en `ronde`. */
export default async function ChecklistPrintRedirect({ params, searchParams }: PrintRedirectProps) {
  const { customerId } = await params
  const query = toQueryString(await searchParams)
  redirect(`/dashboard/livegang/seo-geo/${encodeURIComponent(customerId)}/checklist/print${query}`)
}
