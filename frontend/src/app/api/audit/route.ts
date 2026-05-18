import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

export async function GET(request: NextRequest) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { searchParams } = new URL(request.url)
  const backendUrl = getBackendApiUrl()

  try {
    const response = await fetch(
      `${backendUrl}/api/audit?${searchParams.toString()}`,
      {
        method: "GET",
        headers: { Authorization: userId },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon audits niet ophalen.")
      return NextResponse.json({ error }, { status: response.status })
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch (error) {
    const details =
      error instanceof Error ? error.message : "Backend verbinding mislukt."
    return NextResponse.json(
      { error: `Backend niet bereikbaar (${backendUrl}). Details: ${details}` },
      { status: 502 }
    )
  }
}

export async function POST(request: NextRequest) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Ongeldige request body." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  try {
    const response = await fetch(`${backendUrl}/api/audit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: userId,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const error = await readBackendError(response, "Kon audit niet starten.")
      return NextResponse.json({ error }, { status: response.status })
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch (error) {
    const details =
      error instanceof Error ? error.message : "Backend verbinding mislukt."
    return NextResponse.json(
      { error: `Backend niet bereikbaar (${backendUrl}). Details: ${details}` },
      { status: 502 }
    )
  }
}
