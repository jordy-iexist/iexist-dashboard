import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

const FORWARDED_PARAMS = [
  "scope",
  "customer_website_id",
  "created_from",
  "created_to",
] as const

export async function GET(request: NextRequest) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const backendUrl = new URL(`${getBackendApiUrl()}/api/blogs/ids`)
  for (const param of FORWARDED_PARAMS) {
    const value = request.nextUrl.searchParams.get(param)
    if (value) {
      backendUrl.searchParams.set(param, value)
    }
  }

  const response = await fetch(backendUrl, {
    method: "GET",
    headers: { Authorization: userId },
    cache: "no-store",
  })

  if (!response.ok) {
    const error = await readBackendError(response, "Kon blogs niet ophalen.")
    return NextResponse.json({ error }, { status: response.status })
  }

  return NextResponse.json(await response.json())
}
