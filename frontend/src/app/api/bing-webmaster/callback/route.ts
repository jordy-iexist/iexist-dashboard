import { cookies } from "next/headers"
import { NextRequest, NextResponse } from "next/server"

import { getAuthenticatedUserId, getBackendApiUrl, readBackendError } from "@/lib/backend-api"
import { BING_OAUTH_COOKIE, BING_OAUTH_COOKIE_PATH, bingReturnUrl, parseBingOAuthCookie } from "@/lib/bing-oauth"

/**
 * Antwoord zonder redirect, zodat de code in de adresbalk blijft staan. Dat is
 * nodig voor lokaal testen: Bing stuurt altijd naar de productie-URL, en daar
 * ontbreekt de cookie van de lokale browser.
 */
function stay(message: string, status = 400) {
  return new NextResponse(
    `${message}\n\nStart de koppeling opnieuw bij fase 4 van een klant (Koppel Bing Webmaster).\n\n` +
      "Lokaal aan het testen? Vervang in de adresbalk https://app.iexist.nl door http://localhost:3000 " +
      "(binnen 5 minuten) en druk op Enter.",
    { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } }
  )
}

function clearCookie(response: NextResponse) {
  response.cookies.set(BING_OAUTH_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: BING_OAUTH_COOKIE_PATH,
    maxAge: 0,
  })
  return response
}

/**
 * Redirect-URI van de Bing Webmaster OAuth-client. Controleert de nonce uit de
 * cookie, laat de backend de code inwisselen en stuurt terug naar fase 4.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const pending = parseBingOAuthCookie((await cookies()).get(BING_OAUTH_COOKIE)?.value)
  if (!pending) {
    return stay("Deze Bing-koppeling is niet in deze browser gestart, of is verlopen.")
  }
  // Bing documenteert `state` niet. Komt hij terug, dan moet hij kloppen; anders
  // is de cookie (alleen gezet door /connect in deze browser) de controle.
  const state = params.get("state")
  if (state !== null && state !== pending.nonce) {
    return clearCookie(stay("De Bing-koppeling hoort niet bij deze sessie (state komt niet overeen)."))
  }

  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return stay("Je bent niet (meer) ingelogd in het dashboard. Log in en open deze pagina opnieuw.", 401)
  }

  if (params.get("error")) {
    const denied = params.get("error") === "access_denied"
    return clearCookie(
      NextResponse.redirect(
        bingReturnUrl(pending.customer, denied ? "geweigerd" : "fout", denied ? undefined : `Bing meldt: ${params.get("error")}`)
      )
    )
  }
  const code = params.get("code")
  if (!code) {
    return clearCookie(NextResponse.redirect(bingReturnUrl(pending.customer, "fout", "Bing gaf geen autorisatiecode terug.")))
  }

  try {
    const response = await fetch(`${getBackendApiUrl()}/api/launch-checklist/bing-webmaster/exchange`, {
      method: "POST",
      headers: { Authorization: authorization, "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
      cache: "no-store",
    })
    if (!response.ok) {
      const error = await readBackendError(response, "De koppeling met Bing is mislukt.")
      return clearCookie(NextResponse.redirect(bingReturnUrl(pending.customer, "fout", error)))
    }
  } catch {
    return clearCookie(NextResponse.redirect(bingReturnUrl(pending.customer, "fout", "De backend is niet bereikbaar.")))
  }
  return clearCookie(NextResponse.redirect(bingReturnUrl(pending.customer, "gekoppeld")))
}
