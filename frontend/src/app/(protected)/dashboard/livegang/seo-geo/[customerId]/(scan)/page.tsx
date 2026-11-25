import { redirect } from "next/navigation"

import { ScanIndexRedirect } from "@/components/livegang/ScanPhasePage"
import { toQueryString, type PageSearchParams } from "@/lib/search-params"
import { seoGeoSectionHref, seoGeoSlugFromLegacyFase } from "@/lib/seo-geo-sections"

export const metadata = {
  title: "SEO/GEO-scan",
}

type SeoGeoScanIndexProps = {
  params: Promise<{ customerId: string }>
  searchParams: Promise<PageSearchParams>
}

/**
 * Adres van de klant zonder onderdeel. Een oude `?fase=` (Monday-items, bladwijzers) gaat naar de
 * eigen pagina van dat onderdeel, met de overige parameters (`tab`, `ronde`, `url`, `bing`, ...).
 * Anders door naar de verste gestarte fase; dat weet pas de client (fasestatus uit de layout).
 */
export default async function SeoGeoScanIndex({ params, searchParams }: SeoGeoScanIndexProps) {
  const { customerId } = await params
  const { fase, ...rest } = await searchParams
  const slug = seoGeoSlugFromLegacyFase(Array.isArray(fase) ? fase[0] : fase)
  if (slug) redirect(`${seoGeoSectionHref(customerId, slug)}${toQueryString(rest)}`)

  return <ScanIndexRedirect />
}
