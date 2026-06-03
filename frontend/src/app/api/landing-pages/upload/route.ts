import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

export async function POST(req: NextRequest) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const formData = await req.formData()
    const file = formData.get("file")

    if (!(file instanceof File)) {
      return NextResponse.json(
        { error: "Geen bestand opgegeven." },
        { status: 400 }
      )
    }

    const backendFormData = new FormData()
    backendFormData.append("file", file)

    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/upload`,
      {
        method: "POST",
        headers: {
          Authorization: authorization,
        },
        body: backendFormData,
      }
    )

    if (!response.ok) {
      const backendError = await readBackendError(
        response,
        "Bestand verwerken in backend mislukt."
      )
      return NextResponse.json(
        { error: backendError },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    )
  }
}
