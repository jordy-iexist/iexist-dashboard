import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

export async function POST(request: NextRequest) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json(
      { error: "Ongeldige request body." },
      { status: 400 }
    )
  }

  const backendUrl = getBackendApiUrl()
  const response = await fetch(`${backendUrl}/api/landing-pages/delete/batch`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: userId,
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const error = await readBackendError(response, "Batch verwijderen is mislukt.")
    return NextResponse.json({ error }, { status: response.status })
  }

  return NextResponse.json(await response.json())
}
