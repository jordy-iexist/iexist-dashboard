import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string; columnId: string }>
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id, columnId } = await context.params
  if (!id?.trim() || !columnId?.trim()) {
    return NextResponse.json(
      { error: "Klant id of kolom id ontbreekt." },
      { status: 400 }
    )
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
      `${backendUrl}/api/customers/${encodeURIComponent(id)}/sheet/columns/${encodeURIComponent(columnId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: userId,
        },
        body: JSON.stringify(body),
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon kolom niet bijwerken.")
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

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id, columnId } = await context.params
  if (!id?.trim() || !columnId?.trim()) {
    return NextResponse.json(
      { error: "Klant id of kolom id ontbreekt." },
      { status: 400 }
    )
  }

  const backendUrl = getBackendApiUrl()
  try {
    const response = await fetch(
      `${backendUrl}/api/customers/${encodeURIComponent(id)}/sheet/columns/${encodeURIComponent(columnId)}`,
      {
        method: "DELETE",
        headers: {
          Authorization: userId,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon kolom niet verwijderen.")
      return NextResponse.json({ error }, { status: response.status })
    }

    const payload = await response.json().catch(() => ({ success: true }))
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
