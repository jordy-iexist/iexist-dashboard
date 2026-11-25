// Subpagina's van de SEO/GEO-scan van een klant: fase 1 t/m 4, Monitor en Aanpassingen.
// Eén lijst voor het menu, de fasekaarten in de kop en het doorsturen van oude adressen.
// Vrij van React en iconen, zodat server, client en `active-customer.ts` dit kunnen importeren.

export const SEO_GEO_BASE_URL = "/dashboard/livegang/seo-geo"

export const SEO_GEO_SECTIONS = [
  { slug: "nulmeting", phase: 1, title: "Nulmeting & AI scan", menuTitle: "1. Nulmeting & AI scan" },
  { slug: "geo-checklist", phase: 2, title: "GEO/SEO-checklist", menuTitle: "2. GEO/SEO-checklist" },
  { slug: "content", phase: 3, title: "Content & onpage", menuTitle: "3. Content & onpage" },
  { slug: "kwartaal", phase: 4, title: "Kwartaal GEO", menuTitle: "4. Kwartaal GEO" },
  // Doorlopend en per pagina: geen fasenummer, altijd bereikbaar.
  { slug: "monitor", phase: null, title: "Monitor", menuTitle: "Monitor" },
  { slug: "aanpassingen", phase: null, title: "Aanpassingen", menuTitle: "Aanpassingen" },
] as const

export type SeoGeoSection = (typeof SEO_GEO_SECTIONS)[number]
export type SeoGeoSlug = SeoGeoSection["slug"]
/** Fasenummer van een genummerde fase (1 t/m 4). */
export type SeoGeoPhase = 1 | 2 | 3 | 4

export function isSeoGeoSlug(value: string | null | undefined): value is SeoGeoSlug {
  return SEO_GEO_SECTIONS.some((section) => section.slug === value)
}

/** Adres van een subpagina van de scan voor deze klant. */
export function seoGeoSectionHref(customerId: string, slug: SeoGeoSlug): string {
  return `${SEO_GEO_BASE_URL}/${encodeURIComponent(customerId)}/${slug}`
}

/** Subpagina van een genummerde fase. */
export function seoGeoSlugForPhase(phase: SeoGeoPhase): SeoGeoSlug {
  return SEO_GEO_SECTIONS.find((section) => section.phase === phase)!.slug
}

/**
 * Subpagina bij een oude `?fase=`-waarde (`1` t/m `4`, `monitor`, `aanpassingen`), of null.
 * Zo blijven links van vóór de eigen pagina's werken (Monday-items, bladwijzers).
 */
export function seoGeoSlugFromLegacyFase(fase: string | null | undefined): SeoGeoSlug | null {
  if (!fase) return null
  const section = SEO_GEO_SECTIONS.find(
    (item) => item.slug === fase || (item.phase !== null && String(item.phase) === fase)
  )
  return section?.slug ?? null
}
