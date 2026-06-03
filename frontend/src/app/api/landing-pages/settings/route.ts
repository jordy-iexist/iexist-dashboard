import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

export async function GET() {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const response = await fetch(
    `${getBackendApiUrl()}/api/landing-pages/settings`,
    {
      headers: { Authorization: authorization },
    }
  )

  if (!response.ok) {
    const error = await readBackendError(
      response,
      "Kon instellingen niet ophalen."
    )
    return NextResponse.json({ error }, { status: response.status })
  }

  return NextResponse.json(await response.json())
}

export async function PUT(request: NextRequest) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const body = await request.json().catch(() => null)
  if (!body || typeof body !== "object") {
    return NextResponse.json(
      { error: "Ongeldige request body." },
      { status: 400 }
    )
  }

  const response = await fetch(
    `${getBackendApiUrl()}/api/landing-pages/settings`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: authorization,
      },
      body: JSON.stringify(body),
    }
  )

  if (!response.ok) {
    const error = await readBackendError(
      response,
      "Kon instellingen niet opslaan."
    )
    return NextResponse.json({ error }, { status: response.status })
  }

  return NextResponse.json(await response.json())
}
