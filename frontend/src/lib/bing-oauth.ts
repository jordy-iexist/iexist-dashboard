/**
 * Gedeeld door de Bing Webmaster OAuth-routes (`/api/bing-webmaster/connect` en
 * `/callback`). De `state` van de OAuth-flow is een willekeurige nonce die alleen
 * in een httpOnly-cookie in deze browser staat: de callback vergelijkt beide.
 */

export const BING_OAUTH_COOKIE = "bing_oauth"
/** Alleen de Bing-routes krijgen de cookie mee. */
export const BING_OAUTH_COOKIE_PATH = "/api/bing-webmaster"
/** Bing-autorisatiecodes zijn 5 minuten geldig; iets ruimer voor het inloggen bij Bing. */
export const BING_OAUTH_MAX_AGE_SECONDS = 600

export const CUSTOMER_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

export type BingOAuthCookie = { nonce: string; customer: string | null }

export function parseBingOAuthCookie(value: string | undefined): BingOAuthCookie | null {
  if (!value) return null
  try {
    const parsed = JSON.parse(value) as Partial<BingOAuthCookie>
    if (typeof parsed.nonce !== "string" || parsed.nonce.length < 16) return null
    const customer =
      typeof parsed.customer === "string" && CUSTOMER_ID_PATTERN.test(parsed.customer) ? parsed.customer : null
    return { nonce: parsed.nonce, customer }
  } catch {
    return null
  }
}

/**
 * Pagina waar de gebruiker na het koppelen op terugkomt: fase 4 van de klant,
 * met het resultaat in `?bing=` (gelezen door BingWebmasterSetting).
 * De basis komt uit NEXT_PUBLIC_SITE_URL: in Docker klopt de host van het verzoek niet.
 */
export function bingReturnUrl(customer: string | null, result: "gekoppeld" | "geweigerd" | "fout", detail?: string) {
  const base = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"
  const url = new URL(customer ? `/dashboard/livegang/${customer}` : "/dashboard/livegang", base)
  if (customer) url.searchParams.set("fase", "4")
  url.searchParams.set("bing", result)
  if (detail) url.searchParams.set("bing_melding", detail.slice(0, 300))
  return url
}
