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

  const blogId = request.nextUrl.searchParams.get("blog_id")
  const limit = request.nextUrl.searchParams.get("limit")
  const query = new URLSearchParams()
  if (blogId?.trim()) {
    query.set("blog_id", blogId.trim())
  }
  if (limit?.trim()) {
    query.set("limit", limit.trim())
  }

  const backendUrl = getBackendApiUrl()
  const url = `${backendUrl}/api/publications${
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
    const error = await readBackendError(response, "Kon publicaties niet ophalen.")
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
