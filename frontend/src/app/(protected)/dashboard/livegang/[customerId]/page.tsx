import { redirect } from "next/navigation"

import { toQueryString, type PageSearchParams } from "@/lib/search-params"

type LivegangKlantRedirectProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

/**
 * Oud adres van de SEO/GEO-scan van een klant. Blijft bestaan omdat deze links
 * al in Monday-items staan; `fase`, `tab`, `ronde`, `bing` e.d. gaan mee.
 */
export default async function LivegangKlantRedirect({ params, searchParams }: LivegangKlantRedirectProps) {
  const { customerId } = await params
  const query = toQueryString(await searchParams)
  redirect(`/dashboard/livegang/seo-geo/${encodeURIComponent(customerId)}${query}`)
}
