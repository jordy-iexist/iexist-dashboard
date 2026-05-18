import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ uploadId: string }>
}

export async function GET(_req: NextRequest, context: RouteContext) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const { uploadId } = await context.params
    if (!uploadId?.trim()) {
      return NextResponse.json(
        { error: "Upload id ontbreekt." },
        { status: 400 }
      )
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/uploads/${encodeURIComponent(uploadId)}`,
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
        "Uploadstatus ophalen mislukt."
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
      { error: `Kon uploadstatus niet ophalen: ${message}` },
      { status: 500 }
    )
  }
}
