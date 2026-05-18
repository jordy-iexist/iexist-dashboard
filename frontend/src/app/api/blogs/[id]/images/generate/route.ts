import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function POST(_request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Blog id ontbreekt." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  const response = await fetch(
    `${backendUrl}/api/blogs/${encodeURIComponent(id)}/images/generate`,
    {
      method: "POST",
      headers: {
        Authorization: userId,
      },
    }
  )

  if (!response.ok) {
    const error = await readBackendError(
      response,
      "Afbeelding genereren is mislukt."
    )
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
