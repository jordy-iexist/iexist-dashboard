import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function POST(request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Klant id ontbreekt." }, { status: 400 })
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
    const response = await fetch(
      `${backendUrl}/api/customers/${encodeURIComponent(id)}/sheet/columns`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: userId,
        },
        body: JSON.stringify(body),
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon kolom niet toevoegen.")
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
