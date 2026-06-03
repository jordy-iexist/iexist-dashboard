import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ uploadId: string }>
}

export async function POST(_request: NextRequest, context: RouteContext) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const { uploadId } = await context.params

    const response = await fetch(
      `${getBackendApiUrl()}/api/csv/uploads/${encodeURIComponent(uploadId)}/dismiss`,
      {
        method: "POST",
        headers: {
          Authorization: authorization,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Verbergen mislukt.")
      return NextResponse.json({ error }, { status: response.status })
    }

    return new Response(null, { status: 204 })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon upload niet verbergen: ${message}` },
      { status: 500 }
    )
  }
}
