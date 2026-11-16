import { redirect } from "next/navigation"

import { toQueryString, type PageSearchParams } from "@/lib/search-params"

/** Oud adres van de SEO/GEO-scan: doorsturen met behoud van de query-string. */
export default async function LivegangRedirect({ searchParams }: { searchParams: Promise<PageSearchParams> }) {
  redirect(`/dashboard/livegang/seo-geo${toQueryString(await searchParams)}`)
}
