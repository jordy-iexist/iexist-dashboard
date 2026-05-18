import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function POST(request: NextRequest, context: RouteContext) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { id } = await context.params
  if (!id?.trim()) {
    return NextResponse.json({ error: "Blog id ontbreekt." }, { status: 400 })
  }

  const incomingFormData = await request.formData()
  const file = incomingFormData.get("file")
  if (!(file instanceof File)) {
    return NextResponse.json(
      { error: "Geen afbeelding gekozen." },
      { status: 400 }
    )
  }

  const backendFormData = new FormData()
  backendFormData.append("file", file)

  const backendUrl = getBackendApiUrl()
  const response = await fetch(
    `${backendUrl}/api/blogs/${encodeURIComponent(id)}/images/upload`,
    {
      method: "POST",
      headers: {
        Authorization: userId,
      },
      body: backendFormData,
    }
  )

  if (!response.ok) {
    const error = await readBackendError(
      response,
      "Uploaden van afbeelding is mislukt."
    )
    return NextResponse.json({ error }, { status: response.status })
  }

  const payload = await response.json()
  return NextResponse.json(payload)
}
