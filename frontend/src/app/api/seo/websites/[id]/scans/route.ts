import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function GET(request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Website id ontbreekt." }, { status: 400 })
  }

  const limit = request.nextUrl.searchParams.get("limit")
  const query = new URLSearchParams()
  if (limit?.trim()) {
    query.set("limit", limit.trim())
  }

  const backendUrl = getBackendApiUrl()
  const url = `${backendUrl}/api/seo/websites/${encodeURIComponent(id)}/scans${
    query.size > 0 ? `?${query.toString()}` : ""
  }`
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Authorization: userId,
    },
    cache: "no-store",
  })

  if (!response.ok) {
    const error = await readBackendError(response, "Kon scans niet ophalen.")
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
