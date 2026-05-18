import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ uploadId: string }>
}

export async function POST(_request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { uploadId } = await context.params
  if (!uploadId?.trim()) {
    return NextResponse.json({ error: "Upload id ontbreekt." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  try {
    const response = await fetch(
      `${backendUrl}/api/csv/uploads/${encodeURIComponent(uploadId)}/cancel`,
      {
        method: "POST",
        headers: { Authorization: userId },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon upload niet annuleren.")
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