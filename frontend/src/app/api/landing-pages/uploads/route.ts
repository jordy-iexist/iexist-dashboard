import { NextResponse } from "next/server"

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

  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/uploads`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      const backendError = await readBackendError(
        response,
        "Recente uploads ophalen mislukt."
      )
      return NextResponse.json(
        { error: backendError },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon recente uploads niet ophalen: ${message}` },
      { status: 500 }
    )
  }
}
