import { NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function POST(_request: Request, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Scan id ontbreekt." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  try {
    const response = await fetch(
      `${backendUrl}/api/seo/scans/${encodeURIComponent(id)}/cancel`,
      {
        method: "POST",
        headers: {
          Authorization: userId,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon scan niet annuleren.")
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
