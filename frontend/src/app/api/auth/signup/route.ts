import { NextRequest, NextResponse } from "next/server"

import { setAccessTokenCookie } from "@/lib/auth-session"
import { type AuthTokenResponse } from "@/lib/auth-types"
import { getBackendApiUrl, readBackendError } from "@/lib/backend-api"

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json(
      { error: "Ongeldige request body." },
      { status: 400 }
    )
  }

  try {
    const response = await fetch(`${getBackendApiUrl()}/api/auth/signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Account aanmaken mislukt."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    const payload = (await response.json().catch(() => null)) as
      | AuthTokenResponse
      | null
    if (!payload?.access_token) {
      return NextResponse.json(
        { error: "Onverwachte response van backend." },
        { status: 502 }
      )
    }

    const nextResponse = NextResponse.json({
      user: payload.user,
    })
    setAccessTokenCookie(nextResponse, payload.access_token)
    return nextResponse
  } catch (error) {
    const details =
      error instanceof Error ? error.message : "Backend verbinding mislukt."
    return NextResponse.json(
      { error: `Kon account niet aanmaken. Details: ${details}` },
      { status: 502 }
    )
  }
}
