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
    return NextResponse.json({ error: "Run id ontbreekt." }, { status: 400 })
  }

  const limit = request.nextUrl.searchParams.get("limit")
  const offset = request.nextUrl.searchParams.get("offset")
  const reviewStatus = request.nextUrl.searchParams.get("review_status")
  const query = new URLSearchParams()
  if (limit?.trim()) {
    query.set("limit", limit.trim())
  }
  if (offset?.trim()) {
    query.set("offset", offset.trim())
  }
  if (reviewStatus?.trim()) {
    query.set("review_status", reviewStatus.trim())
  }

  const backendUrl = getBackendApiUrl()
  const url = `${backendUrl}/api/seo/meta-runs/${encodeURIComponent(id)}/pages${
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
    const error = await readBackendError(response, "Kon meta pagina's niet ophalen.")
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
