// Gedeelde helpers voor de actieve klant (een rij uit `customer_websites`).
// Vrij van React en `next/headers`, zodat server en client dit kunnen
// importeren. De server-only cookielezer staat in `active-customer.server.ts`.

import { isSeoGeoSlug, seoGeoSectionHref } from "@/lib/seo-geo-sections"
import { WORK_BOARD_URL, workBoardHref } from "@/lib/work-queue"

export const ACTIVE_CUSTOMER_COOKIE = "active_customer_id"
export const ACTIVE_CUSTOMER_STORAGE_KEY = "active_customer_id"

const COOKIE_MAX_AGE = 60 * 60 * 24 * 365

export type CustomerSection =
  | "home"
  | "profiel"
  | "analyses"
  | "contentBriefs"
  | "searchConsole"
  | "maandrapport"
  | "zoekwoordConcurrenten"
  | "seoGeo"
  | "oplevering"
  | "analytics"
  | "blogs"
  | "landingPages"

// Lege waarde en "none" (items zonder klant) tellen niet als klant.
function normalizeId(value: string | null | undefined): string | null {
  const id = value?.trim()
  if (!id || id === "none") return null
  return id
}

function segmentsOf(pathname: string): string[] {
  return pathname.split("/").filter(Boolean)
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

const LIVEGANG_SUBSECTIONS = new Set(["seo-geo", "oplevering", "analytics"])

export function customerIdFromLocation(
  pathname: string,
  searchParams: { get(name: string): string | null }
): string | null {
  const [root, section, first, second] = segmentsOf(pathname)
  if (root !== "dashboard") return null

  if (section === "klanten") {
    if (!first || first === "nieuw") return null
    return normalizeId(decodeSegment(first))
  }

  if (section === "livegang") {
    if (first === "seo-geo" || first === "oplevering") {
      return second ? normalizeId(decodeSegment(second)) : null
    }
    if (first === "analytics") {
      return normalizeId(searchParams.get("klant"))
    }
    // Oud adres: /dashboard/livegang/{id}
    if (first && !LIVEGANG_SUBSECTIONS.has(first)) {
      return normalizeId(decodeSegment(first))
    }
    return null
  }

  // Alleen de lijstpagina's zelf, niet detail of upload.
  if ((section === "blogs" || section === "landing-pages") && !first) {
    return normalizeId(searchParams.get("customer_website_id"))
  }

  return null
}

export function customerHref(
  section: CustomerSection,
  customerId: string
): string {
  const id = encodeURIComponent(customerId)
  switch (section) {
    case "home":
      return `/dashboard/klanten/${id}`
    case "profiel":
      return `/dashboard/klanten/${id}/profiel`
    case "analyses":
      return `/dashboard/klanten/${id}/analyses`
    case "contentBriefs":
      return `/dashboard/klanten/${id}/content-briefs`
    case "searchConsole":
      return `/dashboard/klanten/${id}/search-console`
    case "maandrapport":
      return `/dashboard/klanten/${id}/maandrapport`
    case "zoekwoordConcurrenten":
      return `/dashboard/klanten/${id}/zoekwoorden/concurrenten`
    case "seoGeo":
      return `/dashboard/livegang/seo-geo/${id}`
    case "oplevering":
      return `/dashboard/livegang/oplevering/${id}`
    case "analytics":
      return `/dashboard/livegang/analytics?klant=${id}`
    case "blogs":
      return `/dashboard/blogs?customer_website_id=${id}`
    case "landingPages":
      return `/dashboard/landing-pages?customer_website_id=${id}`
  }
}

// Het onderdeel met een klantversie waar dit pad onder valt, of null.
export function sectionFromPathname(pathname: string): CustomerSection | null {
  const [root, section, first, second, , fourth] = segmentsOf(pathname)
  if (root !== "dashboard") return null

  if (section === "klanten") {
    if (!first || first === "nieuw") return null
    // Content briefs: het overzicht, en de brief zelf (die onder een analyse hangt).
    if (second === "content-briefs") return "contentBriefs"
    if (second === "analyses" && fourth === "brief") return "contentBriefs"
    // Search Console-inzichten; klant wisselen blijft op dit scherm.
    if (second === "search-console") return "searchConsole"
    // Maandrapport; klant wisselen blijft op dit scherm (de gekozen maand vervalt).
    if (second === "maandrapport") return "maandrapport"
    // Klantprofiel (het oude adres /bewerken stuurt door); klant wisselen blijft op het profiel.
    if (second === "profiel" || second === "bewerken") return "profiel"
    // Zoekwoorden › Concurrenten; klant wisselen blijft op dit scherm.
    if (second === "zoekwoorden") return "zoekwoordConcurrenten"
    // Concurrentieanalyse (lijst, wizard en resultaat); klant wisselen gaat naar de lijst.
    return second === "analyses" ? "analyses" : "home"
  }
  if (section === "livegang") {
    if (first === "seo-geo") return "seoGeo"
    if (first === "oplevering") return "oplevering"
    if (first === "analytics") return "analytics"
    // Oud adres /dashboard/livegang/{id} stuurt door naar de SEO/GEO-scan.
    if (first) return "seoGeo"
    return null
  }
  if (section === "blogs" && !first) return "blogs"
  if (section === "landing-pages" && !first) return "landingPages"
  return null
}

// Adres van hetzelfde onderdeel voor een andere klant; anders de klantpagina.
export function switchHref(pathname: string, newCustomerId: string): string {
  const [root, section, first, second, third, ...rest] = segmentsOf(pathname)

  if (root === "dashboard") {
    // Werkvoorraad (bureaubreed): op het bord blijven, gefilterd op de nieuwe klant.
    if (`/${root}/${section ?? ""}` === WORK_BOARD_URL) {
      return workBoardHref({ customerId: newCustomerId })
    }
    // Subpagina van de SEO/GEO-scan: dezelfde subpagina van de nieuwe klant.
    // Het basisadres en de printpagina gaan zoals de rest naar het basisadres.
    if (
      section === "livegang" &&
      first === "seo-geo" &&
      second &&
      isSeoGeoSlug(third) &&
      rest.length === 0
    ) {
      return seoGeoSectionHref(newCustomerId, third)
    }
    // Analytics-subpagina's (rapporten, vergelijken) houden hun eigen subpad.
    if (section === "livegang" && first === "analytics" && second) {
      const path = `/${segmentsOf(pathname).join("/")}`
      return `${path}?klant=${encodeURIComponent(newCustomerId)}`
    }
    // Losse blog/landingspagina of upload: terug naar de lijst van de nieuwe klant.
    if (section === "blogs" && first) {
      return customerHref("blogs", newCustomerId)
    }
    if (section === "landing-pages" && first) {
      return customerHref("landingPages", newCustomerId)
    }
  }

  return customerHref(sectionFromPathname(pathname) ?? "home", newCustomerId)
}

// Event binnen het tabblad, zodat lezers van sessionStorage een wijziging zien
// (het `storage`-event vuurt alleen in andere tabbladen).
const ACTIVE_CUSTOMER_EVENT = "active-customer-change"

// Alleen in de browser: onthoud de klant voor dit tabblad en als laatst gekozen.
export function persistActiveCustomer(customerId: string): void {
  let changed = false
  try {
    const previous = window.sessionStorage.getItem(ACTIVE_CUSTOMER_STORAGE_KEY)
    if (previous !== customerId) {
      window.sessionStorage.setItem(ACTIVE_CUSTOMER_STORAGE_KEY, customerId)
      changed = true
    }
  } catch {
    // sessionStorage kan geblokkeerd zijn; de cookie volstaat dan
  }
  writeActiveCustomerCookie(customerId)
  if (changed) {
    window.dispatchEvent(new Event(ACTIVE_CUSTOMER_EVENT))
  }
}

// Alleen in de browser: luister naar wijzigingen van de tabblad-klant
// (bedoeld voor `useSyncExternalStore`).
export function subscribeTabCustomer(onChange: () => void): () => void {
  window.addEventListener(ACTIVE_CUSTOMER_EVENT, onChange)
  return () => window.removeEventListener(ACTIVE_CUSTOMER_EVENT, onChange)
}

// Alleen in de browser: zet de cookie (laatst gekozen klant, voor de server).
export function writeActiveCustomerCookie(customerId: string): void {
  try {
    document.cookie = `${ACTIVE_CUSTOMER_COOKIE}=${encodeURIComponent(
      customerId
    )}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`
  } catch {
    // geen document (server) of cookies geblokkeerd
  }
}

// Alleen in de browser: de klant van dit tabblad uit sessionStorage.
export function readTabCustomerId(): string | null {
  try {
    return normalizeId(
      window.sessionStorage.getItem(ACTIVE_CUSTOMER_STORAGE_KEY)
    )
  } catch {
    return null
  }
}
