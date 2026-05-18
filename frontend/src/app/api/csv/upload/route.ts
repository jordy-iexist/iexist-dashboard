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
    const mapping = formData.get("mapping")
    const template = formData.get("template")
    const imageGenerationColumn = formData.get("image_generation_column")

    if (!(file instanceof File)) {
      return NextResponse.json(
        { error: "No file provided" },
        { status: 400 }
      )
    }

    if (typeof mapping !== "string" || !mapping.trim()) {
      return NextResponse.json(
        { error: "No mapping provided" },
        { status: 400 }
      )
    }

    const backendFormData = new FormData()
    backendFormData.append("file", file)
    backendFormData.append("mapping", mapping.trim())
    backendFormData.append(
      "template",
      typeof template === "string" ? template : ""
    )
    backendFormData.append(
      "image_generation_column",
      typeof imageGenerationColumn === "string"
        ? imageGenerationColumn.trim()
        : ""
    )

    const response = await fetch(`${getBackendApiUrl()}/api/csv/upload`, {
      method: "POST",
      headers: {
        Authorization: authorization,
      },
      body: backendFormData,
    })

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
