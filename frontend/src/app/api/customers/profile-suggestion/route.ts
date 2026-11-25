import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

// "Aanvullen vanuit website (AI)": de backend leest de website en geeft een profielvoorstel
// terug. Duurt meestal 15–45 seconden, soms ruim 2 minuten; daarom geen eigen time-out.
export async function POST(request: NextRequest) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json(
      { error: "Ongeldige request body." },
      { status: 400 }
    )
  }

  const backendUrl = getBackendApiUrl()
  try {
    const response = await fetch(`${backendUrl}/api/customers/profile-suggestion`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: userId,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    })

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Kon het profiel niet aanvullen vanuit de website."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch (error) {
    const details =
      error instanceof Error ? error.message : "Backend verbinding mislukt."
    return NextResponse.json(
      {
        error: `Backend niet bereikbaar (${backendUrl}). Details: ${details}`,
      },
      { status: 502 }
    )
  }
}
