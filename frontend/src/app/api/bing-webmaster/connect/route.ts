import { NextRequest, NextResponse } from "next/server"

import { getAuthenticatedUserId, getBackendApiUrl, readBackendError } from "@/lib/backend-api"
import {
  BING_OAUTH_COOKIE,
  BING_OAUTH_COOKIE_PATH,
  BING_OAUTH_MAX_AGE_SECONDS,
  CUSTOMER_ID_PATTERN,
  bingReturnUrl,
} from "@/lib/bing-oauth"

/**
 * Start van de Bing Webmaster OAuth-flow: bewaart een nonce in een cookie en
 * stuurt de gebruiker door naar de toestemmingspagina van Bing.
 * `?customer=` is de klant waar de gebruiker daarna op terugkomt.
 */
export async function GET(request: NextRequest) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.redirect(new URL("/login", process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"))
  }

  const customerParam = request.nextUrl.searchParams.get("customer") ?? ""
  const customer = CUSTOMER_ID_PATTERN.test(customerParam) ? customerParam : null
  // Twee UUID's zonder streepjes: 64 hex-tekens, niet te raden.
  const nonce = `${crypto.randomUUID()}${crypto.randomUUID()}`.replaceAll("-", "")

  let authorizeUrl: string
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/launch-checklist/bing-webmaster/authorize-url?state=${nonce}`,
      { headers: { Authorization: authorization }, cache: "no-store" }
    )
    if (!response.ok) {
      const error = await readBackendError(response, "De koppeling met Bing kon niet worden gestart.")
      return NextResponse.redirect(bingReturnUrl(customer, "fout", error))
    }
    authorizeUrl = ((await response.json()) as { url: string }).url
  } catch {
    return NextResponse.redirect(bingReturnUrl(customer, "fout", "De backend is niet bereikbaar."))
  }

  const redirect = NextResponse.redirect(authorizeUrl)
  redirect.cookies.set(BING_OAUTH_COOKIE, JSON.stringify({ nonce, customer }), {
    httpOnly: true,
    // Lax: de cookie gaat mee als Bing de browser terugstuurt naar de callback.
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: BING_OAUTH_COOKIE_PATH,
    maxAge: BING_OAUTH_MAX_AGE_SECONDS,
  })
  return redirect
}
