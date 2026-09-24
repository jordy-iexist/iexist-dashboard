import { NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function GET(_request: Request, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json(
      { error: "WordPress site id ontbreekt." },
      { status: 400 }
    )
  }

  const backendUrl = getBackendApiUrl()
  const response = await fetch(
    `${backendUrl}/api/wordpress/sites/${encodeURIComponent(id)}/categories`,
    {
      headers: { Authorization: userId },
      cache: "no-store",
    }
  )

  if (!response.ok) {
    const error = await readBackendError(
      response,
      "Kon WordPress categorieën niet ophalen."
    )
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
