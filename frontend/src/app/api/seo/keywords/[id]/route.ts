import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Keyword id ontbreekt." }, { status: 400 })
  }

  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json(
      { error: "Ongeldige request body." },
      { status: 400 }
    )
  }

  const backendUrl = getBackendApiUrl()
  const response = await fetch(
    `${backendUrl}/api/seo/keywords/${encodeURIComponent(id)}`,
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
    const error = await readBackendError(response, "Kon keyword niet bijwerken.")
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Keyword id ontbreekt." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  const response = await fetch(
    `${backendUrl}/api/seo/keywords/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
      headers: {
        Authorization: userId,
      },
    }
  )

  if (!response.ok) {
    const error = await readBackendError(response, "Kon keyword niet verwijderen.")
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
